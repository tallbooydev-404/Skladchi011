# Ombor Mahsulot Boshqarish Boti

Telegram boti orqali ombor (sklad) mahsulotlarini kiritish, chiqarish va boshqarishning avtomatlashtirilgan tizimi.

## Xususiyatlari

### Admin Panel

* 🏢 **Filiallar Boshqarish**: Yangi filial qo'shish, tahrirlash, o'chirish
* 📦 **Mahsulot Boshqarish**:

  * Umumiy mahsulotlar
  * Filialga xos mahsulotlar
  * Rasm yuklash imkoniyati
* 📋 **Ro'yxat**: Barcha mahsulotlar va ularning soni

### Foydalanuvchi Panel

* 📥 **Mahsulot Kiritish**: Hoziroq kiritilgan mahsulotlarga qo'shish
* 📤 **Mahsulot Chiqarish**: Kiritilgan mahsulotlardan ayirish
* 📋 **Ro'yxat Ko'rish**: Filial bo'yicha mahsulotlar soni

### Xavfsizlik

\- 👤 Admin tasdiqlagan foydalanuvchilar bot va web ilovaga kira oladi.



\## Web / Mini App havolasi



\- Botdagi \*\*📱 Ilova\*\* tugmasi Telegram Mini App sifatida ochilishi uchun deploy qilingan web manzilni `WEB\_APP\_URL` env o'zgaruvchisiga yozing (masalan: `https://example.onrender.com`).

\- `WEB\_APP\_URL` berilmasa, bot ilova tugmasini yashiradi va tasdiqlangan foydalanuvchiga havola hali sozlanmaganini bildiradi.

\- Admin foydalanuvchi so'rovini tasdiqlaganda avval toifani tanlaydi: \*\*xodim\*\* yoki \*\*mijoz\*\*. Xodimga botdagi user panel va web ilova logini, mijozga esa faqat web ilova logini beriladi.

