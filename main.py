import stripe
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client, Client
from dotenv import load_dotenv
import os

# Load .env
load_dotenv()

app = FastAPI()

# Stripe Secret from .env
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Supabase from .env
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    import requests
    import traceback

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook Error: {e}")

    if event["type"] == "checkout.session.completed":

        session = event["data"]["object"]
        print(session)

        stripe_session_id = session.get("id")

        # email fix
        email = session.get("customer_email") or session["customer_details"]["email"]

        # metadata fix
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")
        plan_name = metadata.get("plan_name")

        # amount fix
        amount = session.get("amount_total", 0)

        # تحديد الحد الأقصى للـ executions
        if plan_name == "Starter":
            max_exe = 2500
        elif plan_name == "Growth":
            max_exe = 6000
        elif plan_name == "Professional":
            max_exe = 15000
        else:
            max_exe = 9999999

        try:
            # تحقق إذا الاشتراك موجود
            existing = (
                supabase.table("subscriptions")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            if existing.data:
                # تحديث الاشتراك الحالي
                supabase.table("subscriptions").update(
                    {
                        "email": email,
                        "plan_name": plan_name,
                        "amount": amount,
                        "status": "paid",
                        "max_exe": max_exe,
                        "exe": 0,
                        "stripe_session_id": stripe_session_id,
                    }
                ).eq("user_id", user_id).execute()
            else:
                # إضافة اشتراك جديد
                supabase.table("subscriptions").insert(
                    {
                        "user_id": user_id,
                        "email": email,
                        "plan_name": plan_name,
                        "amount": amount,
                        "status": "paid",
                        "max_exe": max_exe,
                        "stripe_session_id": stripe_session_id,
                    }
                ).execute()

            # تحقق من شات بوت المستخدم
            chatbot_res = (
                supabase.table("chatbot_iformation")
                .select("*")
                .eq("user_info", user_id)
                .execute()
            )

            if chatbot_res.data:
                chatbot_data = chatbot_res.data[0]

                # تحديث الـ DB
                supabase.table("chatbot_iformation").update(
                    {"checked": False, "paid": True}
                ).eq("user_info", user_id).execute()

                # تمديد القناة تلقائياً إذا كانت مشغلة (checked=False)
                if chatbot_data.get("channel_id") and not chatbot_data.get("checked"):
                    token = chatbot_data.get("token")
                    channel_id = chatbot_data.get("channel_id")

                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    }
                    extend_payload = {
                        "days": 1,
                        "amount": 0,  # التجديد مجاني لأنه مدفوع
                        "currency": "USD",
                        "comment": "Automatic extension due to subscription renewal",
                    }
                    print("webhook: extend for 1 day")
                    extend_url = (
                        f"https://manager.whapi.cloud/channels/{channel_id}/extend"
                    )
                    try:
                        extend_res = requests.post(
                            extend_url, json=extend_payload, headers=headers, timeout=30
                        )
                        if extend_res.status_code == 200:
                            print(
                                f"✅ Channel {channel_id} extended 30 days automatically"
                            )
                        else:
                            print(
                                f"⚠️ Failed to extend channel {channel_id}: {extend_res.text}"
                            )
                    except Exception:
                        print("❌ Error extending channel:")
                        traceback.print_exc()

        except Exception as e:
            print("❌ Supabase error:", e)
            traceback.print_exc()

    return {"status": "ok"}
