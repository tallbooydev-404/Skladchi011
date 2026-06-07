# Ombor Mahsulot Boshqarish Boti

Telegram boti orqali ombor (sklad) mahsulotlarini kiritish, chiqarish va boshqarishning avtomatlashtirilgan tizimi.

## 🎯 Yangi Xususiyatlari (v2.0)

### 📦 Ko'p Mahsulotli Buyurtmalar
- Bir buyurtmada bir nechta mahsulot qo'shish imkoniyati
- Har bir mahsulot uchun alohida narx va miqdor
- Real-time buyurtma jami narxini hisoblash
- Xaridor va mahsulot qidirish (autocomplete)

### 👷 Ishbay Kategoriyalari
- Xodimlarning turli turshundagi ishbay kategoriyalarini boshqarish
- Har bir kategoriyaga xizmat narxini belgilash
- Mahsulot tannarxiga ishbay xaraji qo'shish

### 💱 Valyuta Kursları
- Turli valyutalar orasidagi konversiya
- USD, EUR, RUB, KZT va boshqa valyutalar
- Kurslarni tarixiy saqlab qolish

### 📊 Yangilangan Hisobot
- Davriy sotuv va foyda hisobi
- Mahsulotlar bo'yicha sotuv tahlili
- Foydalilik koeffisiyenti
- Grafiklar va vizualizatsiya

### 🔒 Xodim Kimslik Boshqarish
- Xodimlardan xarajat va hisobot axborati yashirish
- Employee-specific dashboard va order view

## Xususiyatlari

### Admin Panel

* 🏢 **Filiallar Boshqarish**: Yangi filial qo'shish, tahrirlash, o'chirish
* 📦 **Mahsulot Boshqarish**:

  * Umumiy mahsulotlar
  * Filialga xos mahsulotlar
  * Rasm yuklash imkoniyati
  * Xomashyo retsepti (BOM)
  * Ishbay xaraji hisoblash
* 📋 **Ro'yxat**: Barcha mahsulotlar va ularning soni
* 👷 **Xodimlar**: Xodim boshqarish, davomad belgilash
* 💼 **Mijozlar**: Xaridor ma'lumotlarini saqlash
* 💱 **Valyuta Kursları**: Exchange rate boshqarish
* 💸 **Xarajatlar**: Iş xarajatlarini qayd qilish
* 📊 **Hisobot**: Davriy tahlil va foyda hisobi

### Foydalanuvchi Panel

* 📥 **Mahsulot Kiritish**: Hoziroq kiritilgan mahsulotlarga qo'shish
* 📤 **Mahsulot Chiqarish**: Kiritilgan mahsulotlardan ayirish
* 📋 **Ro'yxat Ko'rish**: Filial bo'yicha mahsulotlar soni
* 📦 **Buyurtma Yaratish**: Ko'p mahsulotli buyurtma

### Xavfsizlik

\- 👤 Admin tasdiqlagan foydalanuvchilar bot va web ilovaga kira oladi.



\## Web / Mini App havolasi



\- Botdagi \*\*📱 Ilova\*\* tugmasi Telegram Mini App sifatida ochilishi uchun deploy qilingan web manzilni `WEB\_APP\_URL` env o'zgaruvchisiga yozing (masalan: `https://example.onrender.com`).

\- `WEB\_APP\_URL` berilmasa, bot ilova tugmasini yashiradi va tasdiqlangan foydalanuvchiga havola hali sozlanmaganini bildiradi.

\- Admin foydalanuvchi so'rovini tasdiqlaganda avval toifani tanlaydi: \*\*xodim\*\* yoki \*\*mijoz\*\*. Xodimga botdagi user panel va web ilova logini, mijozga esa faqat web ilova logini beriladi.

## 📖 Qo'shimcha Ma'lumot

Ko'proq tafsilot uchun [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) faylini o'qing.

