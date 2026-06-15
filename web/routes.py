from datetime import datetime
import os

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from config.settings import ADMIN_ID
from database.mongodb import get_db

ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "admin123")

CRM_ROLES = {"admin", "manager", "warehouseman", "employee", "customer"}
ORDER_STATUSES = ["new", "confirmed", "materials_checked", "in_production", "ready", "delivered", "cancelled"]
PAYMENT_METHODS = ["naqd", "karta/terminal", "bank o'tkazma", "qarz"]
ATTENDANCE_STATUSES = ["keldi", "kelmadi", "kechikdi", "sababli yo'q"]


def _display_name(user):
    if not user:
        return "Mehmon"
    username = user.get("username")
    if username and username != "NoUsername":
        return f"@{username}"
    full_name = " ".join(part for part in [user.get("first_name"), user.get("last_name")] if part)
    return full_name or str(user.get("user_id"))


def _current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    if session.get("role") == "admin" and int(user_id) == ADMIN_ID:
        return {"user_id": ADMIN_ID, "username": "admin", "first_name": "Admin", "role": "admin", "approved": True}
    return get_db().get_user(int(user_id))


def _role(user):
    if not user:
        return None
    if int(user.get("user_id", 0)) == ADMIN_ID:
        return "admin"
    return user.get("role") or "customer"


def _login_required(roles=None):
    user = _current_user()
    if not user:
        return None, redirect(url_for("web_login"))
    role = _role(user)
    if roles and role not in roles:
        flash("Bu sahifaga kirish huquqingiz yo'q.", "error")
        return None, redirect(url_for("web_dashboard"))
    return user, None


def _base_context(user=None):
    db = get_db()
    user = user or _current_user()
    warehouses = db.get_all_warehouses()
    selected_warehouse = request.values.get("warehouse") or (warehouses[0]["name"] if warehouses else None)
    return {
        "user": user,
        "role": _role(user),
        "display_name": _display_name(user),
        "warehouses": warehouses,
        "selected_warehouse": selected_warehouse,
        "year": datetime.utcnow().year,
        "order_statuses": ORDER_STATUSES,
        "payment_methods": PAYMENT_METHODS,
    }


def _to_float(value, default=0):
    try:
        return float(str(value or "").replace(",", "."))
    except ValueError:
        return default


def _optional_int(value):
    try:
        return int(value) if str(value or "").strip() else None
    except ValueError:
        return None


def _format_quantity(value):
    """Miqdorlarni Jinja shablonlarida ixcham ko'rsatish uchun filter."""
    if value is None:
        value = 0
    try:
        return format(float(value), "g")
    except (TypeError, ValueError):
        return value


def _status_label(status):
    return {
        "new": "Yangi",
        "confirmed": "Tasdiqlandi",
        "materials_checked": "Xomashyo tekshirildi",
        "in_production": "Ishlab chiqarishda",
        "ready": "Tayyor",
        "delivered": "Yetkazildi",
        "cancelled": "Bekor qilindi",
        "approved": "Tasdiqlangan",
        "in_progress": "Jarayonda",
        "done": "Tugagan",
        "rejected": "Rad etilgan",
    }.get(status, status)


def register_web_routes(app):
    app.secret_key = os.getenv("SECRET_KEY", os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me"))
    app.jinja_env.globals["status_label"] = _status_label
    app.jinja_env.filters["qty"] = _format_quantity
    
    @app.get("/")
    def web_home():
        return redirect(url_for("web_dashboard" if _current_user() else "web_login"))

    @app.get("/login")
    def web_login():
        return render_template("login.html", **_base_context())

    @app.post("/login")
    def web_login_post():
        login = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        if not login or not password:
            flash("Username yoki user_id va parol kiriting.", "error")
            return redirect(url_for("web_login"))

        if login in {str(ADMIN_ID), "admin"} and password == ADMIN_PASSWORD:
            session.clear()
            session.update({"user_id": ADMIN_ID, "role": "admin"})
            return redirect(url_for("web_dashboard"))

        db = get_db()
        user = db.find_user_for_login(login)
        if not user or not user.get("approved"):
            flash("Foydalanuvchi topilmadi yoki admin tasdiqlamagan.", "error")
            return redirect(url_for("web_login"))
        password_hash = user.get("password_hash")
        if not password_hash or not check_password_hash(password_hash, password):
            flash("Parol noto'g'ri.", "error")
            return redirect(url_for("web_login"))
        session.clear()
        session.update({"user_id": user["user_id"], "role": _role(user)})
        return redirect(url_for("web_dashboard"))

    @app.get("/logout")
    def web_logout():
        session.clear()
        flash("Tizimdan chiqdingiz.", "success")
        return redirect(url_for("web_login"))

    @app.get("/dashboard")
    def web_dashboard():
        user, response = _login_required()
        if response:
            return response
        db = get_db()
        ctx = _base_context(user)
        stats = db.get_order_stats()
        report = db.get_crm_report()
        materials = db.get_raw_materials(ctx["selected_warehouse"]) if ctx["selected_warehouse"] else []
        critical = [m for m in materials if m.get("quantity", 0) <= m.get("min_quantity", 0)]
        if ctx["role"] == "customer":
            orders = db.get_orders(customer_id=user["user_id"], limit=8)
        elif ctx["role"] == "employee":
            orders = db.get_orders(employee_view=True, limit=8)
        else:
            orders = db.get_orders(limit=8)
        return render_template("dashboard.html", **ctx, stats=stats, report=report, orders=orders, critical=critical[:8])

    @app.get("/products")
    def web_products():
        return redirect(url_for("web_finished_products"))

    @app.get("/raw-materials")
    def web_raw_materials():
        user, response = _login_required(["admin", "manager", "warehouseman", "employee"])
        if response:
            return response
        ctx = _base_context(user)
        materials = get_db().get_raw_materials(ctx["selected_warehouse"], request.args.get("q"))
        movements = [] if ctx["role"] == "employee" else get_db().get_stock_movements(limit=60)
        return render_template("raw_materials.html", **ctx, materials=materials, movements=movements, q=request.args.get("q", ""))

    @app.post("/raw-materials")
    def web_add_raw_material():
        user, response = _login_required(["admin", "manager", "warehouseman"])
        if response:
            return response
        db = get_db()
        warehouse = request.form.get("warehouse") or None
        material_id = db.add_raw_material(
            request.form.get("name", "").strip(),
            request.form.get("category", "").strip(),
            request.form.get("unit", "dona").strip(),
            warehouse,
            request.form.get("code", "").strip() or None,
            _to_float(request.form.get("avg_cost")),
            _to_float(request.form.get("min_quantity")),
            _to_float(request.form.get("quantity")),
            _display_name(user),
        )
        flash("Xomashyo qo'shildi." if material_id else "Xomashyo mavjud yoki ma'lumot to'liq emas.", "success" if material_id else "error")
        return redirect(url_for("web_raw_materials", warehouse=warehouse))

    @app.post("/raw-materials/<material_id>/stock")
    def web_adjust_raw_material(material_id):
        user, response = _login_required(["admin", "manager", "warehouseman"])
        if response:
            return response
        warehouse = request.form.get("warehouse") or None
        movement_type = request.form.get("type") or "in"
        new_qty = get_db().adjust_raw_material_stock(
            material_id,
            warehouse,
            movement_type,
            _to_float(request.form.get("quantity")),
            _display_name(user),
            request.form.get("note"),
        )
        flash("Sklad yangilandi." if new_qty is not None else "Miqdor noto'g'ri yoki qoldiq yetarli emas.", "success" if new_qty is not None else "error")
        return redirect(url_for("web_raw_materials", warehouse=warehouse))

    @app.get("/finished-products")
    def web_finished_products():
        user, response = _login_required(["admin", "manager", "warehouseman", "employee"])
        if response:
            return response
        ctx = _base_context(user)
        products = get_db().get_finished_products(search=request.args.get("q"))
        materials = get_db().get_raw_materials(ctx["selected_warehouse"]) if ctx["selected_warehouse"] else []
        return render_template("finished_products.html", **ctx, products=products, materials=materials, q=request.args.get("q", ""))

    @app.post("/finished-products")
    def web_add_finished_product():
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        product_id = get_db().add_finished_product(
            request.form.get("name", "").strip(),
            request.form.get("article", "").strip() or None,
            request.form.get("color", "").strip() or None,
            request.form.get("size", "").strip() or None,
            _to_float(request.form.get("sale_price")),
            True,
        )
        flash("Tayyor mahsulot qo'shildi." if product_id else "Mahsulot mavjud yoki ma'lumot to'liq emas.", "success" if product_id else "error")
        return redirect(url_for("web_finished_products"))

    @app.post("/finished-products/<product_id>/bom")
    def web_add_bom_item(product_id):
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        ok = get_db().set_product_bom_item(product_id, request.form.get("material_id"), _to_float(request.form.get("quantity")))
        flash("Retsept yangilandi." if ok else "Retsept uchun mahsulot yoki xomashyo topilmadi.", "success" if ok else "error")
        return redirect(url_for("web_finished_products"))

    @app.post("/bom/<item_id>/delete")
    def web_delete_bom_item(item_id):
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        get_db().delete_product_bom_item(item_id)
        flash("Retsept qatori o'chirildi.", "success")
        return redirect(url_for("web_finished_products"))

    @app.get("/orders")
    def web_orders():
        user, response = _login_required()
        if response:
            return response
        db = get_db()
        ctx = _base_context(user)
        if ctx["role"] == "customer":
            orders = db.get_orders(customer_id=user["user_id"])
        elif ctx["role"] == "employee":
            orders = db.get_orders(employee_view=True)
        else:
            orders = db.get_orders(status=request.args.get("status") or None)
        products = db.get_finished_products(active=True)
        customers = db.get_customers(limit=100)
        return render_template("orders.html", **ctx, orders=orders, products=products, customers=customers, selected_status=request.args.get("status", ""))

    @app.post("/orders")
    def web_create_order():
        user, response = _login_required(["customer", "admin", "manager"])
        if response:
            return response
        db = get_db()
        ctx = _base_context(user)
        product_ids = request.form.getlist("product_id")
        quantities = request.form.getlist("quantity")
        items = []
        for index, product_id in enumerate(product_ids):
            product = db.get_finished_product(product_id)
            quantity = _to_float(quantities[index] if index < len(quantities) else 1, 1)
            if not product or quantity <= 0:
                continue
            unit_price = float(product.get("sale_price") or 0)
            items.append({
                "product_id": str(product["_id"]),
                "product_name": product.get("name"),
                "article": product.get("article"),
                "color": product.get("color"),
                "size": product.get("size"),
                "quantity": quantity,
                "unit_price": unit_price,
                "cost": float(product.get("cost") or 0),
                "total": quantity * unit_price,
            })
        if not items:
            flash("Kamida bitta tayyor mahsulot va miqdorni to'g'ri tanlang.", "error")
            return redirect(url_for("web_orders"))
        if ctx["role"] == "customer":
            customer_id = user["user_id"]
            customer_name = _display_name(user)
            phone = user.get("phone")
            source = "telegram/web"
        else:
            customer = db.get_customer(request.form.get("customer_id")) if request.form.get("customer_id") else None
            customer_name = (customer or {}).get("name") or request.form.get("customer_name", "").strip() or "Noma'lum mijoz"
            phone = (customer or {}).get("phone") or request.form.get("customer_phone", "").strip() or None
            customer_id = str((customer or {}).get("_id") or phone or customer_name)
            source = request.form.get("source") or "admin"
            db.upsert_customer(customer_name, phone=phone, telegram=request.form.get("telegram"), instagram=request.form.get("instagram"), source=source)
        title = ", ".join(f"{item['product_name']} x {item['quantity']:g}" for item in items[:3])
        order_id = db.create_order(
            customer_id,
            customer_name,
            title,
            request.form.get("description", "").strip(),
            request.form.get("warehouse") or ctx["selected_warehouse"],
            request.form.get("branch") or None,
            items,
            source,
            phone,
        )
        flash(f"Buyurtma yaratildi: {order_id}", "success")
        return redirect(url_for("web_orders"))

    @app.post("/orders/<order_id>/status")
    def web_update_order(order_id):
        user, response = _login_required(["admin", "manager", "warehouseman", "employee"])
        if response:
            return response
        status = request.form.get("status")
        role = _role(user)
        allowed = {
            "admin": set(ORDER_STATUSES),
            "manager": {"confirmed", "materials_checked", "ready", "delivered", "cancelled"},
            "warehouseman": {"materials_checked", "in_production"},
            "employee": {"in_production", "ready"},
        }
        if status not in allowed.get(role, set()):
            flash("Bu statusni qo'yish huquqi yo'q.", "error")
            return redirect(url_for("web_orders"))
        ok = get_db().update_order_status(order_id, status, _display_name(user), request.form.get("note"))
        flash("Buyurtma statusi yangilandi." if ok else "Status yangilanmadi. Xomashyo yetarli bo'lmasligi mumkin.", "success" if ok else "error")
        return redirect(url_for("web_orders"))

    @app.post("/orders/<order_id>/payments")
    def web_add_payment(order_id):
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        method = request.form.get("method")
        if method not in PAYMENT_METHODS:
            method = "naqd"
        get_db().add_payment(order_id, _to_float(request.form.get("amount")), method, request.form.get("note"), _display_name(user))
        flash("To'lov qayd qilindi.", "success")
        return redirect(url_for("web_orders"))

    @app.get("/inventory")
    def web_inventory():
        return redirect(url_for("web_raw_materials", warehouse=request.args.get("warehouse")))

    @app.get("/customers")
    def web_customers():
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        customers = get_db().get_customers(request.args.get("q"))
        return render_template("customers.html", **_base_context(user), customers=customers, q=request.args.get("q", ""))

    @app.post("/customers")
    def web_add_customer():
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        get_db().upsert_customer(
            request.form.get("name", "").strip(),
            request.form.get("phone", "").strip() or None,
            _optional_int(request.form.get("user_id")),
            request.form.get("telegram"),
            request.form.get("instagram"),
            request.form.get("facebook"),
            request.form.get("tiktok"),
            request.form.get("whatsapp"),
            request.form.get("source"),
            request.form.get("address"),
        )
        flash("Xaridor saqlandi.", "success")
        return redirect(url_for("web_customers"))

    @app.get("/employees")
    def web_employees():
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        date_text = request.args.get("date") or datetime.utcnow().strftime("%Y-%m-%d")
        employees = get_db().get_employees()
        attendance = {row["employee_id"]: row for row in get_db().get_attendance(date_text, date_text)}
        for employee in employees:
            employee["attendance"] = attendance.get(str(employee["_id"]))
        return render_template("employees.html", **_base_context(user), employees=employees, attendance=attendance, attendance_statuses=ATTENDANCE_STATUSES, selected_date=date_text)

    @app.post("/employees")
    def web_add_employee():
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        get_db().upsert_employee(
            request.form.get("first_name", "").strip(),
            request.form.get("last_name", "").strip() or None,
            request.form.get("phone", "").strip() or None,
            _optional_int(request.form.get("user_id")),
            request.form.get("position"),
            request.form.get("salary_type"),
            request.form.get("can_mark_attendance") == "on",
        )
        flash("Xodim saqlandi.", "success")
        return redirect(url_for("web_employees"))

    @app.post("/employees/<employee_id>/attendance")
    def web_mark_attendance(employee_id):
        user, response = _login_required(["admin", "manager", "employee"])
        if response:
            return response
        status = request.form.get("status")
        if status not in ATTENDANCE_STATUSES:
            flash("Davomad holati noto'g'ri.", "error")
            return redirect(url_for("web_employees"))
        get_db().mark_attendance(employee_id, request.form.get("date"), status, user.get("user_id"), request.form.get("note"))
        flash("Davomad belgilandi.", "success")
        return redirect(url_for("web_employees", date=request.form.get("date")))

    @app.get("/expenses")
    def web_expenses():
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        date_from = request.args.get("from")
        date_to = request.args.get("to")
        expenses = get_db().get_expenses(date_from, date_to)
        return render_template("expenses.html", **_base_context(user), expenses=expenses, date_from=date_from or "", date_to=date_to or "")

    @app.post("/expenses")
    def web_add_expense():
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        get_db().add_expense(
            request.form.get("category", "").strip(),
            _to_float(request.form.get("amount")),
            request.form.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
            request.form.get("description"),
            _display_name(user),
        )
        flash("Xarajat saqlandi.", "success")
        return redirect(url_for("web_expenses"))

    @app.get("/reports")
    def web_reports():
        user, response = _login_required(["admin", "manager"])
        if response:
            return response
        date_from = request.args.get("from")
        date_to = request.args.get("to")
        report = get_db().get_crm_report(date_from, date_to)
        return render_template("reports.html", **_base_context(user), report=report, date_from=date_from or "", date_to=date_to or "")

    @app.get("/management")
    def web_management():
        user, response = _login_required(["admin"])
        if response:
            return response
        users = get_db().get_all_users()
        return render_template("management.html", **_base_context(user), users=users, crm_roles=CRM_ROLES)

    @app.post("/management/users/<int:user_id>")
    def web_update_user(user_id):
        user, response = _login_required(["admin"])
        if response:
            return response
        role = request.form.get("role")
        if role not in CRM_ROLES:
            role = "customer"
        password = request.form.get("password", "").strip()
        approved = request.form.get("approved") == "on"
        password_hash = generate_password_hash(password) if password else None
        get_db().update_user_access(user_id, role=role, password_hash=password_hash, approved=approved)
        flash("Foydalanuvchi yangilandi.", "success")
        return redirect(url_for("web_management"))
