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
PARTNER_API_KEY = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImExZDI2YWYyYmY4MjVmYjI5MzVjNWI3OTY3ZDA3YmYwZTMxZWIxYjcifQ.eyJwYXJ0bmVyIjp0cnVlLCJpc3MiOiJodHRwczovL3NlY3VyZXRva2VuLmdvb2dsZS5jb20vd2hhcGktYTcyMWYiLCJhdWQiOiJ3aGFwaS1hNzIxZiIsImF1dGhfdGltZSI6MTc2MjY5MDcyMCwidXNlcl9pZCI6InRaSVl5UlRHT1ZVNzlIS0NoOWFJRTRoYUhHdTIiLCJzdWIiOiJ0WklZeVJUR09WVTc5SEtDaDlhSUU0aGFIR3UyIiwiaWF0IjoxNzYyNjkwNzIwLCJleHAiOjE4MjMxNzA3MjAsImVtYWlsIjoienVjY2Vzc2FpQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmaXJlYmFzZSI6eyJpZGVudGl0aWVzIjp7ImVtYWlsIjpbInp1Y2Nlc3NhaUBnbWFpbC5jb20iXX0sInNpZ25faW5fcHJvdmlkZXIiOiJwYXNzd29yZCJ9fQ.AN3E7sw--inccWphErgmcT7l5KElJdf7tlth7wzA0ggOiKMnI116b98tV0uaONS9jdu0vR_J6KOahAXx9BDjK0XtwsYWAmVnKicoN2K5_sFlSDwzMJKjdZ0rIxX4E_BWcZwL_PYwVLjdqltn7lZLCLppk9RyZ_Y6D0qF0wwx1LxMq1d5G7Mv8C9u0A9dSBrNR8OLPKqZlpK_WG-FEdYO5T1VgFNeROcTKXPYDkgbi6-LRNeHeOY0d60eHnxtg6FnsckDPnb-AOwxoCvQXrgYMbZuW9iUygZbEUCs679huCZqSNGdkpWzwkziQphDkxkISzyhUoINHf50wvxTpLWjbw"


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
        email = session.get("customer_email") or session["customer_details"]["email"]
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")
        plan_name = metadata.get("plan_name")
        amount = session.get("amount_total", 0)

        # Max executions
        max_exe = {"Starter": 2500, "Growth": 6000, "Professional": 15000}.get(
            plan_name, 9999999
        )

        try:
            # تحديث/إضافة الاشتراك
            existing = (
                supabase.table("subscriptions")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            if existing.data:
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

            # تحقق من وجود القناة
            chatbot_res = (
                supabase.table("chatbot_iformation")
                .select("*")
                .eq("user_info", user_id)
                .execute()
            )
            if chatbot_res.data:
                chatbot_data = chatbot_res.data[0]
                channel_id = chatbot_data.get("channel_id")
                token = chatbot_data.get("token")

                # تحديث paid فقط
                supabase.table("chatbot_iformation").update({"paid": True}).eq(
                    "user_info", user_id
                ).execute()

                # تمديد القناة إذا موجودة
                if channel_id:
                    print(f"webhook: extending channel {channel_id}")
                    headers = {
                        "Authorization": f"Bearer {PARTNER_API_KEY}",
                        "Accept": "application/json",
                    }
                    extend_payload = {
                        "days": 1,
                        "amount": 0,
                        "currency": "USD",
                        "comment": "Automatic extension due to subscription renewal",
                    }
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
                            supabase.table("chatbot_iformation").update(
                                {"checked": False}
                            ).eq("user_info", user_id).execute()
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
