# 📘 ফেসবুক পেজ অটো-পোস্টিং ও এআই চ্যাটবট সম্পূর্ণ সেটআপ গাইড

এই গাইডে একদম শুরু থেকে শেষ পর্যন্ত ধাপে ধাপে দেখানো হয়েছে কীভাবে কোনো টাকা খরচ না করে (১০০% ফ্রিতে) আপনার ফেসবুক পেজে অটো-পোস্টিং এবং এআই মেসেঞ্জার রিপ্লাই চালু করবেন।

---

## 📑 সূচিপত্র
1. [ধাপ ১: ফ্রি Google Gemini API Key নেওয়া](#ধাপ-১-ফ্রি-google-gemini-api-key-নেওয়া)
2. [ধাপ ২: Meta Developer App তৈরি করা](#ধাপ-২-meta-developer-app-তৈরি-করা)
3. [ধাপ ৩: পেজের Never-Expiring (স্থায়ী) Access Token বের করা](#ধাপ-৩-পেজের-never-expiring-স্থায়ী-access-token-বের-করা)
4. [ধাপ ৪: পেজ আইডি (Page ID) বের করা](#ধাপ-৪-পেজ-আইডি-page-id-বের-করা)
5. [ধাপ ৫: লোকাল কম্পিউটারে রান ও টেস্ট করা](#ধাপ-৫-লোকাল-কম্পিউটারে-রান-ও-টেস্ট-করা)
6. [ধাপ ৬: Render.com-এ ২৪/৭ ফ্রিতে হোস্ট করা](#ধাপ-৬-rendercom-এ-২৪৭-ফ্রিতে-হোস্ট-করা)
7. [ধাপ ৭: ফেসবুক মেসেঞ্জার Webhook কানেক্ট করা](#ধাপ-৭-ফেসবুক-মেসেঞ্জার-webhook-কানেক্ট-করা)
8. [কাস্টমাইজেশন: নলেজবেস ও পোস্টের টপিক পরিবর্তন](#কাস্টমাইজেশন-নলেজবেস-ও-পোস্টের-টপিক-পরিবর্তন)

---

## ধাপ ১: ফ্রি Google Gemini API Key নেওয়া

১. আপনার ব্রাউজারে যান: **[https://aistudio.google.com/](https://aistudio.google.com/)**
২. আপনার জিমেইল (Google Account) দিয়ে লগইন করুন।
৩. বাম পাশের মেন্যু থেকে **"Get API key"** বাটনে ক্লিক করুন।
৪. **"Create API key"**-তে ক্লিক করে যেকোনো একটি প্রজেক্ট সিলেক্ট করুন বা নতুন প্রজেক্ট তৈরি করুন।
৫. আপনার একটি ইউনিক API Key তৈরি হবে। সেটি কপি করে নিরাপদ জায়গায় সংরক্ষণ করুন।

---

## ধাপ ২: Meta Developer App তৈরি করা

১. যান: **[https://developers.facebook.com/](https://developers.facebook.com/)**
২. আপনার ফেসবুক আইডি দিয়ে লগইন করুন। যদি প্রথমবার হন, তবে **Get Started / Register**-এ ক্লিক করে ডেভেলপার অ্যাকাউন্ট চালু করুন।
৩. উপরের ডান পাশে **My Apps**-এ ক্লিক করুন।
৪. **Create App** বাটনে ক্লিক করুন।
৫. Use Case হিসেবে **"Other"** সিলেক্ট করে Next দিন।
৬. App Type হিসেবে **"Business"** সিলেক্ট করুন এবং Next দিন।
৭. আপনার অ্যাপের নাম দিন (যেমন: `My Page Auto Bot`) এবং আপনার ইমেইল দিয়ে **Create App** বাটনে ক্লিক করুন।

---

## ধাপ ৩: পেজের Never-Expiring (স্থায়ী) Access Token বের করা

> ⚠️ **জরুরি নোট**: সাধারণ টোকেন ১ ঘণ্টা বা কয়েকদিন পর মেয়াদ শেষ হয়ে যায়। তাই নিচের পদ্ধতিটি অনুসরণ করে একটি **স্থায়ী (Never Expiring)** টোকেন তৈরি করুন:

১. যান Graph API Explorer-এ: **[https://developers.facebook.com/tools/explorer/](https://developers.facebook.com/tools/explorer/)**
২. উপরে ডান পাশে **Meta App** ড্রপডাউনে আপনার তৈরি করা অ্যাপটি সিলেক্ট করুন।
৩. **User or Page** ড্রপডাউনে ক্লিক করে **"Get Page Access Token"** দিন এবং আপনার ফেসবুক পেজটি সিলেক্ট করুন।
৪. **Permissions** অপশনে ক্লিক করে নিচের পারমিশনগুলো যুক্ত করুন:
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
   - `pages_messaging`
৫. নিচে **Generate Access Token** বাটনে ক্লিক করুন এবং ফেসবুকে অনুমতি কনফার্ম করুন।
৬. এবার এই টোকেনটিকে স্থায়ী করতে:
   - যান: **[https://developers.facebook.com/tools/debug/accesstoken/](https://developers.facebook.com/tools/debug/accesstoken/)**
   - টোকেনটি পেস্ট করে **Debug** বাটনে চাপুন।
   - নিচে স্ক্রল করে **Extend Access Token** বাটনে ক্লিক করুন (এটি ৬০ দিনের জন্য ভ্যালিড হবে)।
   - এবার Graph API Explorer-এ গিয়ে GET ফিল্ডে লিখুন: `me/accounts?fields=name,access_token,id` এবং **Submit** চাপুন।
   - আপনার পেজের নামের পাশে যে `access_token` আসবে—সেটিই হলো আপনার **Never-Expiring (চিরস্থায়ী) Page Access Token**! এটি কপি করে সংরক্ষণ করুন।

---

## ধাপ ৪: পেজ আইডি (Page ID) বের করা

১. আপনার ফেসবুক পেজে যান।
২. পেজের **About** সেকশনে যান।
৩. **Page Transparency** বা **Contact and Basic info**-তে গেলে **Page ID** (একটি সংখ্যা, যেমন: `108392817291...`) দেখতে পাবেন।
৪. অথবা আগের ধাপে `me/accounts` সাবমিট করার পরও পেজের নামের পাশে `"id"` দেখতে পাবেন।

---

## ধাপ ৫: লোকাল কম্পিউটারে রান ও টেস্ট করা

১. প্রজেক্ট ফোল্ডারে `.env.example` ফাইলটির একটি কপি বানিয়ে সেটির নাম দিন `.env`।
২. `.env` ফাইলে আপনার সংগৃহীত কি ও টোকেনগুলো বসিয়ে সেভ করুন:
   ```env
   GEMINI_API_KEY=আপনার_জেমিনি_এপিআই_কি
   FB_PAGE_ID=আপনার_পেজ_আইডি
   FB_PAGE_ACCESS_TOKEN=আপনার_পেজ_এক্সেস_টোকেন
   FB_VERIFY_TOKEN=my_fb_verify_token_2026
   DEFAULT_POST_TOPIC=Islamic knowledge, daily life ethics, peace, and inspiring Sunnah reminders
   POST_SCHEDULE_HOUR=10
   POST_SCHEDULE_MINUTE=0
   IMAGE_PROVIDER=pollinations
   ```
৩. টার্মিনালে ভার্চুয়াল এনভায়রনমেন্ট চালু করে সার্ভার রান করুন:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
৪. ব্রাউজারে `http://localhost:8000` ওপেন করলে সুন্দর স্ট্যাটাস ড্যাশবোর্ড দেখতে পাবেন।
৫. ড্যাশবোর্ডের **"⚡ তাৎক্ষণিক টেস্ট পোস্ট করুন"** বাটনে ক্লিক করে আপনি সরাসরি পেজে পোস্ট টেস্ট করতে পারেন!

---

## ধাপ ৬: Render.com-এ ২৪/৭ ফ্রিতে হোস্ট করা

যাতে আপনার কম্পিউটার বন্ধ থাকলেও ক্লাউডে সার্বক্ষণিক অটোমেশন চালু থাকে:

১. এই প্রজেক্টটি আপনার **GitHub** অ্যাকাউন্টে একটি নতুন রিপোজিটরিতে পুশ করুন:
   ```bash
   git init
   git add .
   git commit -m "Facebook automation setup"
   git remote add origin https://github.com/আপনার_ইউজারনেম/আপনার_রিপো_নাম.git
   git branch -M main
   git push -u origin main
   ```
২. যান: **[https://render.com/](https://render.com/)** এবং ফ্রিতে অ্যাকাউন্ট খুলুন (GitHub দিয়ে লগইন করতে পারেন)।
৩. ড্যাশবোর্ডে **New +** বাটনে ক্লিক করে **Web Service** সিলেক্ট করুন।
৪. আপনার GitHub রিপোজিটরিটি সিলেক্ট করুন।
৫. সেটিংস দিন:
   - **Name**: `fb-page-ai-automation`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`
৬. নিচে **Environment Variables** সেকশনে আপনার `.env` ফাইলের ভ্যারিয়েবলগুলো অ্যাড করুন:
   - `GEMINI_API_KEY`
   - `FB_PAGE_ACCESS_TOKEN`
   - `FB_PAGE_ID`
   - `FB_VERIFY_TOKEN` (যেমন: `my_fb_verify_token_2026`)
   - `DEFAULT_POST_TOPIC`
   - `IMAGE_PROVIDER` (দিন: `pollinations`)
৭. **Deploy Web Service**-এ ক্লিক করুন। ২-৩ মিনিটের মধ্যে আপনার সার্ভিস লাইভ হয়ে যাবে এবং একটি পাবলিক URL পাবেন (যেমন: `https://fb-page-ai-automation.onrender.com`)।

---

## ধাপ ৭: ফেসবুক মেসেঞ্জার Webhook কানেক্ট করা

১. আবার যান: **[https://developers.facebook.com/](https://developers.facebook.com/)** এবং আপনার অ্যাপে প্রবেশ করুন।
২. বাম পাশের মেন্যু থেকে **Add Product**-এ ক্লিক করে **Messenger** সিলেক্ট করুন (বা সরাসরি Messenger সেটিংস এ যান)।
৩. **Webhooks** সেকশনে যান এবং **Add Callback URL** বা **Configure** বাটনে ক্লিক করুন।
৪. দুইটি ইনপুট দেখতে পাবেন:
   - **Callback URL**: `https://আপনার-রেন্ডার-ইউআরএল.onrender.com/webhook` (যেমন: `https://fb-page-ai-automation.onrender.com/webhook`)
   - **Verify Token**: `.env`-এ যে টোকেনটি দিয়েছিলেন (যেমন: `my_fb_verify_token_2026`)
৫. **Verify and Save** বাটনে ক্লিক করুন। সাথে সাথে ফেসবুক আপনার সার্ভারের সাথে কানেক্ট হয়ে ভেরিফাই করে নিবে!
৬. এবার **Subscription fields** অপশনে ক্লিক করে নিচের ফিল্ডগুলো টিক দিয়ে সেভ করুন:
   - `messages` (গ্রাহকের মেসেজ পাওয়ার জন্য)
   - `messaging_postbacks`
৭. এরপর নিচে **Page Subscriptions** অংশে আপনার ফেসবুক পেজটি **Subscribe** করে দিন।

🎉 **অভিনন্দন! আপনার ফেসবুক পেজে অটোমেশন সম্পন্ন হয়েছে!**
এখন পেজে কেউ মেসেজ দিলেই এআই নলেজবেস অনুযায়ী সাথে সাথে সুন্দর বাংলায় উত্তর দিবে, এবং প্রতিদিন নির্ধারিত সময়ে আকর্ষণীয় ছবি সহ স্বয়ংক্রিয়ভাবে পোস্ট হবে।

---

## কাস্টমাইজেশন: নলেজবেস ও পোস্টের টপিক পরিবর্তন

### ১. এআই চ্যাটবটের তথ্য বদলাতে:
- প্রজেক্টের `knowledge_base.txt` ফাইলে আপনার পেজ/প্রতিষ্ঠানের নাম, যোগাযোগের ফোন নম্বর, ঠিকানা, সচরাচর জিজ্ঞাসিত প্রশ্ন ও উত্তরগুলো পরিবর্তন করে সেভ করলেই চ্যাটবট নতুন তথ্য জেনে যাবে।

### ২. স্বয়ংক্রিয় পোস্টের টপিক বদলাতে:
- `.env` বা Render-এর Environment Variable-এ `DEFAULT_POST_TOPIC` ফিল্ডে আপনার পছন্দের টপিক লিখে দিন (যেমন: "প্রতিদিনের স্বাস্থ্য ও পুষ্টি টিপস" বা "ই-কমার্স পণ্যের অফার ও রিভিউ")।
- এআই প্রতিদিন নতুন ও ইউনিক ক্যাপশন এবং সেই অনুযায়ী মানানসই ছবি জেনারেট করে পোস্ট করবে।

---

## ধাপ ৮: গুগল শিট (Google Sheets) দিয়ে কনটেন্ট প্ল্যান করা (১০০% ফ্রি)

আপনি যদি চান আপনার তৈরি করা আইডিয়াগুলো গুগল শিটে লিখে রাখবেন এবং এআই সেই শিটের টপিক ধরে ধরে স্বয়ংক্রিয় ড্রাফট বানিয়ে ড্যাশবোর্ডে সাজিয়ে রাখবে:

### ১. গুগল শিট তৈরি করুন:
একটি নতুন Google Sheet খুলুন এবং প্রথম সারিতে (Row 1) নিচের কলামগুলো লিখুন:
| A | B | C | D | E |
| :--- | :--- | :--- | :--- | :--- |
| **Topic** | **Caption** | **Media_Type** | **Media_URL** | **Status** |
| Top 5 AI Tools | | photo | | pending |
| Python Automation Tips | | video | https://example.com/demo.mp4 | pending |
| Digital Skill Reminder | | text | | pending |

- **Topic:** পোস্টের মূল বিষয়বস্তু বা আইডিয়া।
- **Caption (ঐচ্ছিক):** আপনি যদি চান নিজের লেখা ক্যাপশন দিতে পারেন, অথবা খালি রাখলে এআই স্বয়ংক্রিয়ভাবে আকর্ষণীয় ক্যাপশন বানিয়ে নিবে।
- **Media_Type:** `photo`, `video`, অথবা `text`।
- **Media_URL (ঐচ্ছিক):** সরাসরি ছবি বা ভিডিওর লিঙ্ক।
- **Status:** যে পোস্টগুলো এখনো হয়নি সেগুলোতে `pending` লিখবেন, আর যা পোস্ট হয়ে গেছে সেগুলোতে `posted` বা `done` লিখে দিতে পারেন।

### ২. শিটের লিঙ্ক কপি করুন:
- শিটের উপরে ডানপাশে **Share** বাটনে ক্লিক করুন।
- **General access** অপশনে **"Anyone with the link"** (Viewer) সিলেক্ট করুন।
- **Copy link** দিয়ে লিঙ্কটি কপি করুন।

### ৩. ড্যাশবোর্ডে পেস্ট করুন:
- আপনার ওয়েবসাইটের ড্যাশবোর্ডে **"📊 গুগল শিট থেকে কন্টেন্ট ইমপোর্ট"** বক্সে লিঙ্কটি পেস্ট করে **"📥 শিট থেকে ড্রাফট ইমপোর্ট করুন"** বাটনে ক্লিক করুন।
- সাথে সাথে গুগল শিট থেকে সব কনটেন্ট পড়ে এআই ড্রাফট আকারে সাজিয়ে আপনার অনুমোদনের অপেক্ষায় রেখে দেবে!
