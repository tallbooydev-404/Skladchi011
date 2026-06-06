
from datetime import datetime
import logging

from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from config.settings import DB_NAME, MONGO_URI, WAREHOUSE_NAME

logger = logging.getLogger(__name__)

class DatabaseNotInitializedError(RuntimeError):
    """MongoDB manager ishga tushmaganida qaytariladigan aniq xato."""

class MongoDBManager:
    """MongoDB bilan ishlash uchun asosiy klass"""
    
    def __init__(self):
        try:
            self.client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            self.client.admin.command("ping")
            self.db = self.client[DB_NAME]
            self._create_collections()
            logger.info("✅ MongoDB ulanishi muvaffaqiyatli")
        except Exception as e:
            logger.error(f"❌ MongoDB ulanish xatosi: {e}")
            raise

    def _create_collections(self):
        """Kerakli kolleksiyalar va indekslarni tayyorlash."""
        collections = [
            "users",
            "warehouses",
            "branches",
            "product_types",
            "products",
            "inventory",
            "requests",
            "units",
            "groups",
            "orders",
            "employees",
            "customers",
            "raw_materials",
            "finished_products",
            "product_boms",
            "stock_balances",
            "stock_movements",
            "expenses",
            "payments",
            "attendance",
        ]
        for name in collections:
            if name not in self.db.list_collection_names():
                self.db.create_collection(name)

        # Users / requests
        self.db["users"].create_index("user_id", unique=True)
        self.db["requests"].create_index("user_id", unique=True)
        self.db["orders"].create_index([("status", 1), ("created_at", -1)])
        self.db["orders"].create_index([("customer_id", 1), ("created_at", -1)])
        self.db["employees"].create_index("user_id", unique=True, sparse=True)
        self.db["customers"].create_index("user_id", unique=True, sparse=True)
        self.db["customers"].create_index([("phone", 1)], sparse=True)
        self.db["raw_materials"].create_index([("name", 1), ("warehouse", 1), ("branch", 1), ("category", 1)], unique=True)
        self.db["raw_materials"].create_index("legacy_product_id", unique=True, sparse=True)
        self._ensure_finished_products_article_index()
        self.db["finished_products"].create_index([("name", 1), ("color", 1), ("size", 1)], unique=True)
        self.db["product_boms"].create_index([("product_id", 1), ("material_id", 1)], unique=True)
        self.db["stock_balances"].create_index([("material_id", 1), ("warehouse", 1)], unique=True)
        self.db["stock_movements"].create_index([("material_id", 1), ("created_at", -1)])
        self.db["expenses"].create_index([("date", -1), ("category", 1)])
        self.db["payments"].create_index([("order_id", 1), ("created_at", -1)])
        self.db["attendance"].create_index([("employee_id", 1), ("date", 1)], unique=True)
        # Warehouse/branch/type/product unique constraints per kontekst
        # Legacy tizimlarda branches uchun faqat `name` unique index qolib ketgan bo'lishi mumkin.
        # Bu holatda turli skladlarda bir xil filial nomi qo'shib bo'lmaydi, shuning uchun tozalaymiz.
        branch_indexes = self.db["branches"].index_information()
        for index_name, index_data in branch_indexes.items():
            if index_name == "_id_":
                continue
            if index_data.get("unique") and index_data.get("key") == [("name", 1)]:
                self.db["branches"].drop_index(index_name)

        self.db["warehouses"].create_index([("name", 1)], unique=True)
        self.db["branches"].create_index([("name", 1), ("warehouse", 1)], unique=True)
        self.db["product_types"].create_index([("name", 1), ("warehouse", 1), ("branch", 1)], unique=True)
        self.db["products"].create_index([("name", 1), ("warehouse", 1), ("branch", 1), ("product_type", 1)], unique=True)
        self.db["units"].create_index([("name", 1)], unique=True)
        self.db["groups"].create_index([("warehouse", 1), ("group_id", 1)], unique=True)
        inventory_indexes = self.db["inventory"].index_information()
        for index_name, index_data in inventory_indexes.items():
            if index_name == "_id_":
                continue
            if index_data.get("unique") and index_data.get("key") == [("product_name", 1), ("branch", 1)]:
                self.db["inventory"].drop_index(index_name)

        self.db["inventory"].create_index(
            [("product_name", 1), ("warehouse", 1), ("branch", 1), ("product_type", 1)],
            unique=True,
        )
        self._migrate_legacy_products_to_raw_materials()

    def _ensure_finished_products_article_index(self):
        """Tayyor mahsulot artikuli uchun null/bo'sh qiymatlarga chidamli unique index."""
        collection = self.db["finished_products"]

        # Eski yozuvlarda article=None yoki article="" bo'lsa sparse unique index baribir
        # DuplicateKeyError berishi mumkin. Bunday qiymatlar unique indexga kirmasligi
        # uchun fieldni butunlay olib tashlaymiz.
        collection.update_many(
            {"$or": [{"article": None}, {"article": ""}]},
            {"$unset": {"article": ""}},
        )

        for index_name, index_data in collection.index_information().items():
            if index_name == "_id_":
                continue
            if index_data.get("key") != [("article", 1)]:
                continue
            if index_data.get("partialFilterExpression") == {"article": {"$type": "string", "$gt": ""}}:
                continue
            collection.drop_index(index_name)

        collection.create_index(
            [("article", 1)],
            unique=True,
            name="uniq_finished_products_article_non_empty",
            partialFilterExpression={"article": {"$type": "string", "$gt": ""}},
        )    

    def _migrate_legacy_products_to_raw_materials(self):
        """Eski products/inventory yozuvlarini yangi xomashyo modeliga ko'chiradi."""
        for product in self.db["products"].find({}):
            legacy_id = str(product["_id"])
            material = {
                "legacy_product_id": legacy_id,
                "name": product.get("name"),
                "code": product.get("code"),
                "category": product.get("product_type") or "Umumiy",
                "unit": product.get("unit") or "dona",
                "warehouse": product.get("warehouse"),
                "branch": product.get("branch") or "common",
                "avg_cost": float(product.get("avg_cost") or 0),
                "min_quantity": float(product.get("min_quantity") or 0),
                "active": True,
                "created_at": product.get("created_at") or datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            self.db["raw_materials"].update_one(
                {"legacy_product_id": legacy_id},
                {"$setOnInsert": material},
                upsert=True,
            )

        for item in self.db["inventory"].find({}):
            material = self.db["raw_materials"].find_one(
                {
                    "name": item.get("product_name"),
                    "warehouse": item.get("warehouse"),
                    "branch": item.get("branch") or "common",
                    "category": item.get("product_type") or "Umumiy",
                }
            )
            if not material:
                continue
            self.db["stock_balances"].update_one(
                {"material_id": str(material["_id"]), "warehouse": item.get("warehouse")},
                {
                    "$setOnInsert": {
                        "material_id": str(material["_id"]),
                        "warehouse": item.get("warehouse"),
                        "quantity": float(item.get("quantity") or 0),
                        "updated_at": datetime.utcnow(),
                    }
                },
                upsert=True,
            )


    # ==================== USERS ====================
    
    def add_user(self, user_id, username, first_name, approved=False):
        try:
            self.db["users"].insert_one(
                {
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "approved": approved,
                    "created_at": datetime.utcnow(),
                }
            )
            return True
        except DuplicateKeyError:
            return False

    def get_user(self, user_id):
        return self.db["users"].find_one({"user_id": user_id})

    def update_user_contact(self, user_id, phone=None, first_name=None, last_name=None):
        update = {"updated_at": datetime.utcnow()}
        if phone is not None:
            update["phone"] = phone
        if first_name is not None:
            update["first_name"] = first_name
        if last_name is not None:
            update["last_name"] = last_name
        self.db["users"].update_one({"user_id": user_id}, {"$set": update}, upsert=False)

    def approve_user(self, user_id, role=None, password_hash=None):
        update = {"approved": True, "updated_at": datetime.utcnow()}
        if role is not None:
            update["role"] = role
        if password_hash is not None:
            update["password_hash"] = password_hash
        self.db["users"].update_one({"user_id": user_id}, {"$set": update})

    def reject_user(self, user_id):
        self.db["users"].delete_one({"user_id": user_id})
        
    def get_all_users(self):
        return list(self.db["users"].find({}).sort("created_at", 1))

    def delete_user(self, user_id):
        self.db["users"].delete_one({"user_id": user_id})
        
    def update_user_access(self, user_id, role=None, password_hash=None, approved=None):
        """Web panel uchun foydalanuvchi roli va parolini saqlash."""
        update = {"updated_at": datetime.utcnow()}
        if role is not None:
            update["role"] = role
        if password_hash is not None:
            update["password_hash"] = password_hash
        if approved is not None:
            update["approved"] = approved
        self.db["users"].update_one({"user_id": user_id}, {"$set": update})

    def find_user_for_login(self, login):
        """username yoki user_id orqali web foydalanuvchini topish."""
        query = {"username": login.lstrip("@")}
        if str(login).isdigit():
            query = {"$or": [{"user_id": int(login)}, {"username": login.lstrip("@")}]}
        return self.db["users"].find_one(query)

    # ==================== BRANCHES ====================
    
    # WAREHOUSES
    def add_warehouse(self, name):
        try:
            self.db["warehouses"].insert_one({"name": name, "created_at": datetime.utcnow()})
            return True
        except DuplicateKeyError:
            return False

    def get_all_warehouses(self):
        return list(self.db["warehouses"].find({}).sort("name", 1))

    def update_warehouse(self, old_name, new_name):
        try:
            result = self.db["warehouses"].update_one({"name": old_name}, {"$set": {"name": new_name}})
            if result.modified_count:
                # bog'liq hujjatlarni ham yangilash
                self.db["branches"].update_many({"warehouse": old_name}, {"$set": {"warehouse": new_name}})
                self.db["product_types"].update_many({"warehouse": old_name}, {"$set": {"warehouse": new_name}})
                self.db["products"].update_many({"warehouse": old_name}, {"$set": {"warehouse": new_name}})
                self.db["inventory"].update_many({"warehouse": old_name}, {"$set": {"warehouse": new_name}})
            return result.modified_count > 0
        except DuplicateKeyError:
            return False

    def delete_warehouse(self, name):
        self.db["warehouses"].delete_one({"name": name})
        self.db["branches"].delete_many({"warehouse": name})
        self.db["product_types"].delete_many({"warehouse": name})
        self.db["products"].delete_many({"warehouse": name})
        self.db["inventory"].delete_many({"warehouse": name})
        
    # BRANCHES
    def add_branch(self, name, warehouse=None):
        try:
            self.db["branches"].insert_one(
                {"name": name, "warehouse": warehouse, "created_at": datetime.utcnow()}
            )
            return True
        except DuplicateKeyError:
            return False

    def get_all_branches(self, warehouse=None):
        query = {"warehouse": warehouse} if warehouse is not None else {}
        return list(self.db["branches"].find(query).sort("name", 1))

    def get_branch_by_name(self, name):
        return self.db["branches"].find_one({"name": name})

    def update_branch(self, old_name, new_name, warehouse=None):
        try:
            query = {"name": old_name}
            if warehouse is not None:
                query["warehouse"] = warehouse
            result = self.db["branches"].update_one(query, {"$set": {"name": new_name}})
            if result.modified_count:
                linked_query = {"branch": old_name}
                if warehouse is not None:
                    linked_query["warehouse"] = warehouse
                self.db["product_types"].update_many(linked_query, {"$set": {"branch": new_name}})
                self.db["products"].update_many(linked_query, {"$set": {"branch": new_name}})
                self.db["inventory"].update_many(linked_query, {"$set": {"branch": new_name}})
            return result.modified_count > 0
        except DuplicateKeyError:
            return False

    def delete_branch(self, name, warehouse=None):
        query = {"name": name}
        if warehouse is not None:
            query["warehouse"] = warehouse
        self.db["branches"].delete_one(query)
        linked_query = {"branch": name}
        if warehouse is not None:
            linked_query["warehouse"] = warehouse
        self.db["product_types"].delete_many(linked_query)
        self.db["products"].delete_many(linked_query)
        self.db["inventory"].delete_many(linked_query)

    # PRODUCT TYPES
    def add_product_type(self, name, image_id=None, warehouse=None, branch=None, common_code=None):
        try:
            self.db["product_types"].insert_one(
                {
                    "name": name,
                    "image_id": image_id,
                    "common_code": common_code,
                    "warehouse": warehouse,
                    "branch": branch,
                    "created_at": datetime.utcnow(),
                }
            )
            return True
        except DuplicateKeyError:
            return False

    def get_all_product_types(self, warehouse=None, branch=None):
        query = {}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        return list(self.db["product_types"].find(query).sort("name", 1))

    def get_product_type_by_name(self, name, warehouse=None, branch=None):
        query = {"name": name}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        return self.db["product_types"].find_one(query)

    def get_product_type_by_id(self, type_id, warehouse=None, branch=None):
        query = {"_id": ObjectId(type_id)}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        return self.db["product_types"].find_one(query)
    
    def update_product_type(self, old_name, new_name, image_id=None, warehouse=None, branch=None, common_code=None):
        try:
            query = {"name": old_name}
            if warehouse is not None:
                query["warehouse"] = warehouse
            if branch is not None:
                query["branch"] = branch

            update_data = {"name": new_name}
            if image_id is not None:
                update_data["image_id"] = image_id
            if common_code is not None:
                update_data["common_code"] = common_code


            result = self.db["product_types"].update_one(query, {"$set": update_data})
            if result.modified_count:
                self.db["products"].update_many(
                    {
                        "product_type": old_name,
                        **({"warehouse": warehouse} if warehouse is not None else {}),
                        **({"branch": branch} if branch is not None else {}),
                    },
                    {"$set": {"product_type": new_name}},
                )
                self.db["inventory"].update_many(
                    {
                        "product_type": old_name,
                        **({"warehouse": warehouse} if warehouse is not None else {}),
                        **({"branch": branch} if branch is not None else {}),
                    },
                    {"$set": {"product_type": new_name}},
                )
            return result.modified_count > 0
        except DuplicateKeyError:
            return False

    def update_products_code_by_type(self, product_type, new_code, warehouse=None, branch=None):
        query = {"product_type": product_type}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        result = self.db["products"].update_many(query, {"$set": {"code": new_code}})
        return result.modified_count
    
    def delete_product_type(self, name, warehouse=None, branch=None):
        query = {"name": name}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        self.db["product_types"].delete_one(query)
        self.db["products"].delete_many(
            {
                "product_type": name,
                **({"warehouse": warehouse} if warehouse is not None else {}),
                **({"branch": branch} if branch is not None else {}),
            }
        )
        self.db["inventory"].delete_many(
            {
                "product_type": name,
                **({"warehouse": warehouse} if warehouse is not None else {}),
                **({"branch": branch} if branch is not None else {}),
            }
        )

    # PRODUCTS
    def add_product(self, name, code, product_type, warehouse=None, branch=None, image_id=None, unit="dona"):
        try:
            self.db["products"].insert_one(
                {
                    "name": name,
                    "code": code,
                    "unit": unit or "dona",
                    "product_type": product_type,
                    "warehouse": warehouse,
                    "branch": branch,
                    "image_id": image_id,
                    "created_at": datetime.utcnow(),
                }
            )
            return True
        except DuplicateKeyError:
            return False

    def get_products_by_type(self, warehouse, branch, product_type):
        return list(
            self.db["products"].find(
                {"warehouse": warehouse, "branch": branch, "product_type": product_type}
            ).sort("name", 1)
        )

    def get_products_by_type_all(self, product_type):
        return list(self.db["products"].find({"product_type": product_type}).sort("name", 1))

    def get_product_by_name(self, name, warehouse=None, branch=None, product_type=None):
        query = {"name": name}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        if product_type is not None:
            query["product_type"] = product_type
        return self.db["products"].find_one(query)

    def get_product_by_id(self, product_id, warehouse=None, branch=None, product_type=None):
        query = {"_id": ObjectId(product_id)}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        if product_type is not None:
            query["product_type"] = product_type
        return self.db["products"].find_one(query)
    
    def update_product(self, old_name, new_name, new_code, warehouse=None, branch=None, product_type=None, image_id=None, unit=None):
        query = {"name": old_name}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        if product_type is not None:
            query["product_type"] = product_type
        try:
            update_data = {
               "name": new_name,
               "code": new_code,
           }
            if image_id is not None:
               update_data["image_id"] = image_id
            if unit is not None:
               update_data["unit"] = unit
               
            result = self.db["products"].update_one(
                query,
                {
                "$set": update_data
                },
            )
            if result.modified_count and old_name != new_name:
                self.db["inventory"].update_many(
                    self._inventory_query(old_name, warehouse, branch, product_type),
                    {
                        "$set": {
                            "product_name": new_name,
                            "updated_at": datetime.utcnow(),
                        }
                    },
                )
            return result.modified_count > 0
        except DuplicateKeyError:
            return False

    def delete_product(self, name, warehouse=None, branch=None, product_type=None):
        query = {"name": name}
        if warehouse is not None:
            query["warehouse"] = warehouse
        if branch is not None:
            query["branch"] = branch
        if product_type is not None:
            query["product_type"] = product_type
        self.db["products"].delete_one(query)
    # INVENTORY
    
    def _inventory_query(self, product_name, warehouse=None, branch=WAREHOUSE_NAME, product_type=None):
       query = {"product_name": product_name, "branch": branch}
       if warehouse is not None:
           query["warehouse"] = warehouse
       if product_type is not None:
           query["product_type"] = product_type
       return query

    def get_inventory(self, product_name, warehouse=None, branch=WAREHOUSE_NAME, product_type=None):
       result = self.db["inventory"].find_one(
           self._inventory_query(product_name, warehouse, branch, product_type)
       )
       return result if result else {"quantity": 0}

    def get_inventory_by_branch(self, warehouse=None, branch=WAREHOUSE_NAME):
        query = {"branch": branch}
        if warehouse is not None:
            query["warehouse"] = warehouse
        return list(self.db["inventory"].find(query).sort("product_name", 1))

    
    def get_inventory_by_warehouse(self, warehouse=None):
        query = {}
        if warehouse is not None:
            query["warehouse"] = warehouse
        return list(self.db["inventory"].find(query).sort([("branch", 1), ("product_name", 1)]))

    def get_total_inventory_by_product(self, product_name, warehouse=None, product_type=None):
        return self.get_inventory(product_name, warehouse, WAREHOUSE_NAME, product_type)

    def add_inventory(self, product_name, quantity, warehouse=None, branch=WAREHOUSE_NAME, product_type=None):
        current = self.get_inventory(product_name, warehouse, branch, product_type)
        new_quantity = current.get("quantity", 0) + quantity
        query = self._inventory_query(product_name, warehouse, branch, product_type)
        
        self.db["inventory"].update_one(
            query,
            {
                "$set": {
                    **query,
                    "quantity": new_quantity,
                    "updated_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )
        return new_quantity

    def remove_inventory(self, product_name, quantity, warehouse=None, branch=WAREHOUSE_NAME, product_type=None):
        current = self.get_inventory(product_name, warehouse, branch, product_type)
        current_qty = current.get("quantity", 0)
        if quantity > current_qty:
            return None

        new_quantity = current_qty - quantity
        query = self._inventory_query(product_name, warehouse, branch, product_type)
            
        self.db["inventory"].update_one(
            query,
            {
                "$set": {
                    **query,
                    "quantity": new_quantity,
                    "updated_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )
        return new_quantity

    # ==================== REQUESTS ====================
    
    def add_request(self, user_id, username):
        """So'rov qo'shish"""
        try:
            self.db["requests"].insert_one(
                {
                    "user_id": user_id,
                    "username": username,
                    "status": "pending",
                    "created_at": datetime.utcnow(),
                }
            )
            return True
        except DuplicateKeyError:
            return False

    def delete_request(self, user_id):
        """So'rovni o'chirish"""
        self.db["requests"].delete_one({"user_id": user_id})

 # ==================== UNITS ====================
    def add_unit(self, name):
        try:
            self.db["units"].insert_one({"name": name, "created_at": datetime.utcnow()})
            return True
        except DuplicateKeyError:
            return False

    def get_all_units(self):
        return list(self.db["units"].find({}).sort("name", 1))

    def delete_unit(self, name):
        self.db["units"].delete_one({"name": name})
    
    # ==================== GROUPS ====================
    def add_group(self, warehouse, group_id, group_link, group_name=None):
        try:
            self.db["groups"].update_one(
                {"warehouse": warehouse, "group_id": group_id},
                {
                    "$set": {
                        "warehouse": warehouse,
                        "group_id": group_id,
                        "group_link": group_link,
                        "group_name": group_name or f"Group {group_id}",
                        "updated_at": datetime.utcnow(),
                    },
                    "$setOnInsert": {"created_at": datetime.utcnow()},
                },
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"Guruh qo'shishda xato: {e}")
            return False

    def get_warehouse_groups(self, warehouse):
        return list(self.db["groups"].find({"warehouse": warehouse}).sort("group_name", 1))

    def get_group(self, warehouse, group_id):
        return self.db["groups"].find_one({"warehouse": warehouse, "group_id": group_id})

    def delete_group(self, warehouse, group_id):
        self.db["groups"].delete_one({"warehouse": warehouse, "group_id": group_id})

# ==================== CRM: CUSTOMERS / EMPLOYEES ====================

    def upsert_customer(self, name, phone=None, user_id=None, telegram=None, instagram=None, facebook=None, tiktok=None, whatsapp=None, source=None, address=None):
        query = {"user_id": user_id} if user_id else {"phone": phone, "name": name}
        doc = {
            "name": name,
            "phone": phone,
            "user_id": user_id,
            "telegram": telegram,
            "instagram": instagram,
            "facebook": facebook,
            "tiktok": tiktok,
            "whatsapp": whatsapp,
            "source": source or "manual",
            "address": address,
            "active": True,
            "updated_at": datetime.utcnow(),
        }
        result = self.db["customers"].update_one(
            query,
            {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
        return str(result.upserted_id) if result.upserted_id else None

    def get_customers(self, search=None, limit=200):
        query = {}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"phone": {"$regex": search, "$options": "i"}},
                {"telegram": {"$regex": search, "$options": "i"}},
                {"instagram": {"$regex": search, "$options": "i"}},
            ]
        return list(self.db["customers"].find(query).sort("created_at", -1).limit(limit))

    def get_customer(self, customer_id):
        try:
            return self.db["customers"].find_one({"_id": ObjectId(customer_id)})
        except Exception:
            return None

    def upsert_employee(self, first_name, last_name=None, phone=None, user_id=None, position=None, salary_type="monthly", can_mark_attendance=False):
        query = {"user_id": user_id} if user_id else {"phone": phone, "first_name": first_name}
        doc = {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "user_id": user_id,
            "position": position,
            "salary_type": salary_type or "monthly",
            "can_mark_attendance": bool(can_mark_attendance),
            "active": True,
            "updated_at": datetime.utcnow(),
        }
        result = self.db["employees"].update_one(
            query,
            {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
        return str(result.upserted_id) if result.upserted_id else None

    def get_employees(self, active=None):
        query = {}
        if active is not None:
            query["active"] = active
        return list(self.db["employees"].find(query).sort([("active", -1), ("first_name", 1)]))

    def mark_attendance(self, employee_id, date_text, status, actor_id=None, note=None):
        doc = {
            "employee_id": employee_id,
            "date": date_text,
            "status": status,
            "actor_id": actor_id,
            "note": note,
            "updated_at": datetime.utcnow(),
        }
        self.db["attendance"].update_one(
            {"employee_id": employee_id, "date": date_text},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
        return True

    def get_attendance(self, date_from=None, date_to=None):
        query = {}
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to
        return list(self.db["attendance"].find(query).sort("date", -1))

# ==================== CRM: RAW MATERIALS / STOCK ====================

    def add_raw_material(self, name, category, unit, warehouse=None, code=None, avg_cost=0, min_quantity=0, quantity=0, actor_name=None):
        try:
            doc = {
                "name": name,
                "code": code,
                "category": category or "Umumiy",
                "unit": unit or "dona",
                "warehouse": warehouse,
                "branch": "common",
                "avg_cost": float(avg_cost or 0),
                "min_quantity": float(min_quantity or 0),
                "active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            result = self.db["raw_materials"].insert_one(doc)
            material_id = str(result.inserted_id)
            self.db["stock_balances"].update_one(
                {"material_id": material_id, "warehouse": warehouse},
                {"$set": {"material_id": material_id, "warehouse": warehouse, "quantity": float(quantity or 0), "updated_at": datetime.utcnow()}},
                upsert=True,
            )
            if float(quantity or 0):
                self._add_stock_movement(material_id, warehouse, "in", float(quantity or 0), actor_name, "Boshlang'ich qoldiq")
            return material_id
        except DuplicateKeyError:
            return None

    def get_raw_materials(self, warehouse=None, search=None, active=None, limit=300):
        query = {}
        if warehouse:
            query["warehouse"] = warehouse
        if active is not None:
            query["active"] = active
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"code": {"$regex": search, "$options": "i"}},
                {"category": {"$regex": search, "$options": "i"}},
            ]
        materials = list(self.db["raw_materials"].find(query).sort([("category", 1), ("name", 1)]).limit(limit))
        for material in materials:
            material["quantity"] = self.get_stock_quantity(str(material["_id"]), material.get("warehouse"))
        return materials

    def get_raw_material(self, material_id):
        try:
            material = self.db["raw_materials"].find_one({"_id": ObjectId(material_id)})
            if material:
                material["quantity"] = self.get_stock_quantity(str(material["_id"]), material.get("warehouse"))
            return material
        except Exception:
            return None

    def get_stock_quantity(self, material_id, warehouse=None):
        balance = self.db["stock_balances"].find_one({"material_id": str(material_id), "warehouse": warehouse})
        return float(balance.get("quantity", 0)) if balance else 0.0

    def _add_stock_movement(self, material_id, warehouse, movement_type, quantity, actor_name=None, note=None, order_id=None):
        material = self.get_raw_material(material_id)
        self.db["stock_movements"].insert_one(
            {
                "material_id": str(material_id),
                "material_name": material.get("name") if material else None,
                "warehouse": warehouse,
                "type": movement_type,
                "quantity": float(quantity),
                "actor_name": actor_name,
                "note": note,
                "order_id": order_id,
                "created_at": datetime.utcnow(),
            }
        )

    def adjust_raw_material_stock(self, material_id, warehouse, movement_type, quantity, actor_name=None, note=None, order_id=None):
        material_id = str(material_id)
        qty = float(quantity or 0)
        if qty <= 0:
            return None
        current = self.get_stock_quantity(material_id, warehouse)
        if movement_type == "out":
            if qty > current:
                return None
            new_qty = current - qty
        elif movement_type == "adjust":
            new_qty = qty
        else:
            movement_type = "in"
            new_qty = current + qty
        self.db["stock_balances"].update_one(
            {"material_id": material_id, "warehouse": warehouse},
            {"$set": {"material_id": material_id, "warehouse": warehouse, "quantity": new_qty, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        movement_qty = qty if movement_type != "adjust" else new_qty - current
        self._add_stock_movement(material_id, warehouse, movement_type, movement_qty, actor_name, note, order_id)
        return new_qty

    def get_stock_movements(self, material_id=None, limit=100):
        query = {"material_id": str(material_id)} if material_id else {}
        return list(self.db["stock_movements"].find(query).sort("created_at", -1).limit(limit))

# ==================== CRM: FINISHED PRODUCTS / BOM ====================

    def add_finished_product(self, name, article=None, color=None, size=None, sale_price=0, active=True):
        try:
            doc = {
                "name": name,
                "color": color,
                "size": size,
                "sale_price": float(sale_price or 0),
                "active": bool(active),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            if article:
                doc["article"] = article
            result = self.db["finished_products"].insert_one(
                doc
            )
            return str(result.inserted_id)
        except DuplicateKeyError:
            return None

    def get_finished_products(self, active=None, search=None):
        query = {}
        if active is not None:
            query["active"] = active
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"article": {"$regex": search, "$options": "i"}},
                {"color": {"$regex": search, "$options": "i"}},
                {"size": {"$regex": search, "$options": "i"}},
            ]
        products = list(self.db["finished_products"].find(query).sort("name", 1))
        for product in products:
            product["bom"] = self.get_product_bom(str(product["_id"]))
            product["cost"] = self.calculate_product_cost(str(product["_id"]))
        return products

    def get_finished_product(self, product_id):
        try:
            product = self.db["finished_products"].find_one({"_id": ObjectId(product_id)})
            if product:
                product["bom"] = self.get_product_bom(product_id)
                product["cost"] = self.calculate_product_cost(product_id)
            return product
        except Exception:
            return None

    def set_product_bom_item(self, product_id, material_id, quantity):
        material = self.get_raw_material(material_id)
        product = self.get_finished_product(product_id)
        if not material or not product:
            return False
        self.db["product_boms"].update_one(
            {"product_id": str(product_id), "material_id": str(material_id)},
            {
                "$set": {
                    "product_id": str(product_id),
                    "product_name": product.get("name"),
                    "material_id": str(material_id),
                    "material_name": material.get("name"),
                    "unit": material.get("unit"),
                    "quantity": float(quantity or 0),
                    "updated_at": datetime.utcnow(),
                },
                "$setOnInsert": {"created_at": datetime.utcnow()},
            },
            upsert=True,
        )
        return True

    def delete_product_bom_item(self, item_id):
        try:
            self.db["product_boms"].delete_one({"_id": ObjectId(item_id)})
            return True
        except Exception:
            return False

    def get_product_bom(self, product_id):
        return list(self.db["product_boms"].find({"product_id": str(product_id)}).sort("material_name", 1))

    def calculate_product_cost(self, product_id):
        total = 0.0
        for item in self.get_product_bom(product_id):
            material = self.get_raw_material(item["material_id"])
            total += float(item.get("quantity") or 0) * float((material or {}).get("avg_cost") or 0)
        return total

    def calculate_order_materials(self, items):
        required = {}
        for item in items:
            product_id = str(item.get("product_id"))
            order_qty = float(item.get("quantity") or 0)
            for bom_item in self.get_product_bom(product_id):
                material_id = bom_item["material_id"]
                required.setdefault(
                    material_id,
                    {
                        "material_id": material_id,
                        "material_name": bom_item.get("material_name"),
                        "unit": bom_item.get("unit"),
                        "quantity": 0.0,
                    },
                )
                required[material_id]["quantity"] += float(bom_item.get("quantity") or 0) * order_qty
        return list(required.values())

    def check_material_availability(self, items, warehouse=None):
        rows = []
        ok = True
        for req in self.calculate_order_materials(items):
            have = self.get_stock_quantity(req["material_id"], warehouse)
            enough = have >= req["quantity"]
            ok = ok and enough
            rows.append({**req, "available": have, "enough": enough})
        return ok, rows

# ==================== CRM: EXPENSES / PAYMENTS / REPORTS ====================

    def add_expense(self, category, amount, date_text, description=None, actor_name=None):
        result = self.db["expenses"].insert_one(
            {
                "category": category,
                "amount": float(amount or 0),
                "date": date_text,
                "description": description,
                "actor_name": actor_name,
                "created_at": datetime.utcnow(),
            }
        )
        return str(result.inserted_id)

    def get_expenses(self, date_from=None, date_to=None):
        query = {}
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to
        return list(self.db["expenses"].find(query).sort("date", -1))

    def add_payment(self, order_id, amount, method, note=None, actor_name=None):
        result = self.db["payments"].insert_one(
            {
                "order_id": str(order_id),
                "amount": float(amount or 0),
                "method": method,
                "note": note,
                "actor_name": actor_name,
                "created_at": datetime.utcnow(),
            }
        )
        return str(result.inserted_id)

    def get_payments(self, order_id=None):
        query = {"order_id": str(order_id)} if order_id else {}
        return list(self.db["payments"].find(query).sort("created_at", -1))

    def get_crm_report(self, date_from=None, date_to=None):
        order_query = {}
        if date_from or date_to:
            order_query["date"] = {}
            if date_from:
                order_query["date"]["$gte"] = date_from
            if date_to:
                order_query["date"]["$lte"] = date_to
        orders = list(self.db["orders"].find(order_query))
        expenses = self.get_expenses(date_from, date_to)
        revenue = sum(float(order.get("total_amount") or 0) for order in orders if order.get("status") != "cancelled")
        expense_total = sum(float(exp.get("amount") or 0) for exp in expenses)
        product_sales = {}
        for order in orders:
            for item in order.get("items", []):
                key = item.get("product_name") or "Noma'lum"
                product_sales.setdefault(key, {"quantity": 0.0, "amount": 0.0})
                product_sales[key]["quantity"] += float(item.get("quantity") or 0)
                product_sales[key]["amount"] += float(item.get("total") or 0)
        return {
            "orders_count": len(orders),
            "revenue": revenue,
            "expenses": expense_total,
            "profit": revenue - expense_total,
            "product_sales": product_sales,
        }

# ==================== WEB ORDERS / CRM ====================

    def create_order(self, customer_id, customer_name, title, description, warehouse=None, branch=None, items=None, source="web", phone=None):
        items = items or []
        total_amount = sum(float(item.get("total") or 0) for item in items)
        materials_ok, materials = self.check_material_availability(items, warehouse) if items else (True, [])
        doc = {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "customer_phone": phone,
            "title": title,
            "description": description,
            "warehouse": warehouse,
            "branch": branch,
            "status": "new",
            "source": source,
            "items": items,
            "materials": materials,
            "materials_ok": materials_ok,
            "total_amount": total_amount,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "assigned_to": None,
            "events": [
                {"status": "new", "text": "Buyurtma mijoz tomonidan yuborildi", "at": datetime.utcnow()}
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        result = self.db["orders"].insert_one(doc)
        return str(result.inserted_id)

    def get_orders(self, status=None, customer_id=None, employee_view=False, limit=100):
        query = {}
        if status:
            query["status"] = status
        if customer_id:
            query["customer_id"] = customer_id
        if employee_view:
            query["status"] = {"$in": ["confirmed", "materials_checked", "in_production", "ready", "approved", "in_progress"]}
        return list(self.db["orders"].find(query).sort("created_at", -1).limit(limit))

    def get_order(self, order_id):
        try:
            return self.db["orders"].find_one({"_id": ObjectId(order_id)})
        except Exception:
            return None

    def refresh_order_materials(self, order_id):
        order = self.get_order(order_id)
        if not order:
            return None
        materials_ok, materials = self.check_material_availability(order.get("items", []), order.get("warehouse"))
        self.db["orders"].update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"materials": materials, "materials_ok": materials_ok, "updated_at": datetime.utcnow()}},
        )
        return materials_ok, materials

    def consume_order_materials(self, order_id, actor_name=None):
        order = self.get_order(order_id)
        if not order:
            return False, "Buyurtma topilmadi"
        materials_ok, materials = self.check_material_availability(order.get("items", []), order.get("warehouse"))
        if not materials_ok:
            self.db["orders"].update_one(
                {"_id": ObjectId(order_id)},
                {"$set": {"materials": materials, "materials_ok": False, "updated_at": datetime.utcnow()}},
            )
            return False, "Xomashyo yetarli emas"
        for material in materials:
            new_qty = self.adjust_raw_material_stock(
                material["material_id"],
                order.get("warehouse"),
                "out",
                material["quantity"],
                actor_name,
                f"Buyurtma uchun chiqim: {order.get('title')}",
                str(order["_id"]),
            )
            if new_qty is None:
                return False, "Xomashyo chiqimida xatolik"
        self.db["orders"].update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"materials": materials, "materials_ok": True, "materials_consumed": True, "updated_at": datetime.utcnow()}},
        )
        return True, "Xomashyo chiqim qilindi"

    def update_order_status(self, order_id, status, actor_name, note=None, assigned_to=None):
        event_text = note or status
        if status == "materials_checked":
            self.refresh_order_materials(order_id)
        if status == "in_production":
            order = self.get_order(order_id)
            if order and order.get("items") and not order.get("materials_consumed"):
                ok, message = self.consume_order_materials(order_id, actor_name)
                if not ok:
                    return False
        update = {
            "$set": {"status": status, "updated_at": datetime.utcnow()},
            "$push": {"events": {"status": status, "text": event_text, "actor": actor_name, "at": datetime.utcnow()}},
        }
        if assigned_to is not None:
            update["$set"]["assigned_to"] = assigned_to
        try:
            result = self.db["orders"].update_one({"_id": ObjectId(order_id)}, update)
            return result.modified_count > 0
        except Exception:
            return False

    def get_order_stats(self):
        statuses = ["new", "confirmed", "materials_checked", "in_production", "ready", "delivered", "cancelled", "approved", "done", "rejected"]
        stats = {key: self.db["orders"].count_documents({"status": key}) for key in statuses}
        stats["approved"] = stats.get("approved", 0) + stats.get("confirmed", 0)
        stats["in_progress"] = stats.get("in_progress", 0) + stats.get("in_production", 0)
        stats["done"] = stats.get("done", 0) + stats.get("delivered", 0) + stats.get("ready", 0)
        stats["rejected"] = stats.get("rejected", 0) + stats.get("cancelled", 0)
        stats["total"] = self.db["orders"].count_documents({})
        return stats

# Global
_db_manager = None

def init_db():
    global _db_manager
    _db_manager = MongoDBManager()
    return _db_manager

def get_db():
    if _db_manager is None:
       raise DatabaseNotInitializedError(
           "MongoDB ishga tushmagan. Render envda MONGO_URI to'g'ri berilganini va MongoDB ulanishini tekshiring."
       )
    return _db_manager
