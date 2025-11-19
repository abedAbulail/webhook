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
        email = session.get("customer_email")
        if not email:
            email = session["customer_details"]["email"]

        # metadata fix
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")
        plan_name = metadata.get("plan_name")

        # amount fix
        amount = session.get("amount_total", 0)

        if plan_name == "Starter":
            max = 2500
        elif plan_name == "Growth":
            max = 6000
        elif plan_name == "Professional":
            max = 15000
        else:
            max = 9999999

        try:
            supabase.table("subscriptions").insert(
                {
                    "user_id": user_id,
                    "email": email,
                    "plan_name": plan_name,
                    "amount": amount,
                    "status": "paid",
                    "max_exe":max,
                    "stripe_session_id": stripe_session_id,
                }
            ).execute()
        except Exception as e:
            print("❌ Supabase insert error:", e)

    return {"status": "ok"}

