import os
import tempfile
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import stripe
from dotenv import load_dotenv
import requests
import base64

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# Initialize Flask app and CORS
app = Flask(__name__)
CORS(app,
     resources={r"/*": {"origins": "*"}},
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=True)


# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
PRICE_WEEKLY = "price_1Rlm3I7f2nbXiM5KRNNvniuW"
PRICE_YEARLY = "price_1Rlm6a7f2nbXiM5KqNWebhNO"
KIMI_API_KEY = os.environ.get('KIMI_API_KEY')
KIMI_OPTIMIZE_ENDPOINT = 'https://api.moonshot.ai/v1/cv/optimize'
KIMI_TRANSLATE_ENDPOINT = 'https://api.moonshot.ai/v1/cv/translate'
KIMI_GENERATE_ENDPOINT = 'https://api.moonshot.ai/v1/cv/generate'

MOCK_MODE = os.environ.get('MOCK_MODE', 'false').lower() == 'true'


@app.route("/create-checkout-session", methods=["POST", "OPTIONS"])
def create_checkout_session():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    data = request.get_json()
    plan = data.get("plan")
    user_uid = data.get("user_uid")

    if plan == "weekly":
        price_id = PRICE_WEEKLY
    elif plan == "yearly":
        price_id = PRICE_YEARLY
    else:
        return jsonify({"error": "Invalid plan"}), 400

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{FRONTEND_URL}/subscription-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/",
            metadata={"user_uid": user_uid or "", "plan": plan},
        )
        return jsonify({"url": session.url})
    except Exception as e:
        print(f"Error creating checkout session: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/create-customer-portal-session", methods=["POST", "OPTIONS"])
def create_customer_portal_session():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    data = request.get_json()
    customer_id = data.get("customer_id")
    user_uid = data.get("user_uid")

    if not customer_id:
        return jsonify({"error": "Missing customer_id"}), 400

    print(f"Creating customer portal session for customer: {customer_id}")

    try:
        # Check if customer portal is configured
        try:
            # Create the portal session
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=f"{FRONTEND_URL}/profile",
            )

            print(f"Created customer portal session: {session.url}")

            return jsonify({"url": session.url})
        except stripe.error.InvalidRequestError as portal_error:
            # Check if this is a configuration error
            if "No configuration provided" in str(portal_error):
                print("Customer portal not configured in Stripe Dashboard")
                # Instead of using the portal, create a direct cancel link
                return jsonify({
                    "error": "Customer portal not configured",
                    "message": "Please configure your Stripe Customer Portal in the Stripe Dashboard",
                    "cancel_url": f"{FRONTEND_URL}/cancel-subscription?customer_id={customer_id}"
                })
            else:
                # Re-raise for other errors
                raise portal_error
    except stripe.error.InvalidRequestError as e:
        print(f"Invalid Stripe request: {str(e)}")

        # If the customer doesn't exist, try to find them by email
        if "No such customer" in str(e) and user_uid:
            try:
                # Get the user's email from Firestore
                profile_ref = fs_db.collection("profiles").document(user_uid)
                profile = profile_ref.get()

                if profile.exists:
                    profile_data = profile.to_dict()
                    email = profile_data.get("email")

                    if email:
                        # Try to find the customer by email
                        customers = stripe.Customer.list(
                            limit=1,
                            email=email
                        )

                        if customers and customers.data:
                            customer_id = customers.data[0].id

                            # Update the user's profile with the correct customer ID
                            profile_ref.set({
                                "stripeCustomerId": customer_id
                            }, merge=True)

                            # Create the portal session with the correct customer ID
                            session = stripe.billing_portal.Session.create(
                                customer=customer_id,
                                return_url=f"{FRONTEND_URL}/profile",
                            )

                            print(f"Created customer portal session after finding customer by email: {session.url}")

                            return jsonify({"url": session.url})
            except Exception as inner_e:
                print(f"Error finding customer by email: {str(inner_e)}")

        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Error creating customer portal session: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/create-customer-portal-by-email", methods=["POST", "OPTIONS"])
def create_customer_portal_by_email():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    data = request.get_json()
    email = data.get("email")
    user_uid = data.get("user_uid")

    if not email:
        return jsonify({"error": "Missing email"}), 400

    try:
        # Try to find the customer by email
        customers = stripe.Customer.list(
            limit=1,
            email=email
        )

        if not customers or not customers.data:
            # Create a new customer if none exists
            customer = stripe.Customer.create(
                email=email,
                metadata={"user_uid": user_uid}
            )
            customer_id = customer.id
            print(f"Created new customer {customer_id} for email {email}")
        else:
            customer_id = customers.data[0].id
            print(f"Found existing customer {customer_id} for email {email}")

        # Update the user's profile with the customer ID
        if user_uid:
            profile_ref = fs_db.collection("profiles").document(user_uid)
            profile_ref.set({
                "stripeCustomerId": customer_id
            }, merge=True)
            print(f"Updated user {user_uid} with customer ID {customer_id}")

        # Create the portal session
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{FRONTEND_URL}/profile",
        )

        print(f"Created customer portal session: {session.url}")

        return jsonify({"url": session.url})
    except Exception as e:
        print(f"Error creating customer portal by email: {str(e)}")
        return jsonify({"error": str(e)}), 500
@app.route('/api/optimize-cv', methods=['POST', 'OPTIONS'])
def optimize_cv():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    style = request.form.get('style', 'modern')
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()

    # Save file to temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_in:
        file.save(temp_in.name)
        input_path = temp_in.name

    try:
        # Just return the original file (mock implementation)
        return send_file(
            input_path,
            as_attachment=True,
            download_name=f'optimized-{filename}',
            mimetype='application/pdf' if ext == '.pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        # Clean up if there was an error
        if os.path.exists(input_path):
            os.remove(input_path)
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-cv', methods=['POST', 'OPTIONS'])
def generate_cv():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    template = request.form.get('template', 'modern')
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()

    # Save file to temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_in:
        file.save(temp_in.name)
        input_path = temp_in.name

    try:
        # Just return the original file (mock implementation)
        return send_file(
            input_path,
            as_attachment=True,
            download_name=f'generated-{filename}',
            mimetype='application/pdf' if ext == '.pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        # Clean up if there was an error
        if os.path.exists(input_path):
            os.remove(input_path)
        return jsonify({'error': str(e)}), 500

@app.route('/api/translate-cv', methods=['POST', 'OPTIONS'])
def translate_cv():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    language = request.form.get('language', 'en')
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()

    # Save file to temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_in:
        file.save(temp_in.name)
        input_path = temp_in.name

    try:
        # Just return the original file (mock implementation)
        return send_file(
            input_path,
            as_attachment=True,
            download_name=f'translated-{filename}',
            mimetype='application/pdf' if ext == '.pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        # Clean up if there was an error
        if os.path.exists(input_path):
            os.remove(input_path)
        return jsonify({'error': str(e)}), 500

@app.route('/process_pdf', methods=['POST', 'OPTIONS'])
def process_pdf():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    # Get JSON data from request
    data = request.get_json()
    if not data or 'filedata' not in data or 'filename' not in data:
        return jsonify({'error': 'Missing file data or filename'}), 400

    try:
        # Extract data from request
        filename = data['filename']
        file_content = data['filedata']
        operation = data.get('operation', 'optimize')  # Default to optimize

        # Decode base64 content
        try:
            # Handle both with and without data URL prefix
            if ',' in file_content:
                file_content = file_content.split(',', 1)[1]
            file_bytes = base64.b64decode(file_content)
        except Exception as e:
            return jsonify({'error': f'Invalid base64 encoding: {str(e)}'}), 400

        # Get file extension
        ext = os.path.splitext(filename)[1].lower()
        if not ext:
            ext = '.pdf'  # Default to PDF if no extension

        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_in:
            temp_in.write(file_bytes)
            input_path = temp_in.name

        # Mock response - just return the same file
        # Read the file
        with open(input_path, 'rb') as f:
            processed_content = f.read()

        # Encode as base64
        processed_base64 = base64.b64encode(processed_content).decode('utf-8')

        # Clean up input file
        os.remove(input_path)

        # Return mock response
        return jsonify({
            'success': True,
            'filename': f"{operation}-{filename}",
            'filedata': processed_base64
        })

    except Exception as e:
        print(f"Error processing PDF: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route("/verify-session", methods=["POST", "OPTIONS"])
def verify_session():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    data = request.get_json()
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    try:
        # Retrieve the session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)

        # Get the plan from the session metadata
        metadata = session.get("metadata", {})
        plan = metadata.get("plan") if metadata else None

        # Get the payment status
        payment_status = session.get("payment_status")

        # Get the user_uid from the session metadata
        user_uid = metadata.get("user_uid") if metadata else None

        # Get the customer ID
        customer_id = session.get("customer")

        print(f"Verifying session: {session_id}")
        print(f"Payment status: {payment_status}")
        print(f"User UID: {user_uid}")
        print(f"Plan: {plan}")
        print(f"Customer ID: {customer_id}")

        # If payment is successful, update the subscription in Firebase
        if payment_status == "paid" and user_uid:
            profile_ref = fs_db.collection("profiles").document(user_uid)
            profile_ref.set({
                "stripeCustomerId": customer_id,
                "subscription": {
                    "active": True,
                    "plan": plan,
                    "startedAt": firestore.SERVER_TIMESTAMP,
                    "endsAt": None,
                    "stripeSessionId": session_id
                }
            }, merge=True)

            print(f"Subscription verified and updated for session: {session_id}")

        # Always include the customer_id in the response
        return jsonify({
            "plan": plan,
            "payment_status": payment_status,
            "customer_id": customer_id
        })
    except Exception as e:
        print(f"Error verifying session: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/get-customer-by-email", methods=["POST", "OPTIONS"])
def get_customer_by_email():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"error": "Missing email"}), 400

    try:
        # Try to find the customer ID from Stripe by email
        customers = stripe.Customer.list(
            limit=1,
            email=email
        )

        if not customers or not customers.data:
            return jsonify({"error": "No Stripe customer found with this email"}), 404

        customer_id = customers.data[0].id
        print(f"Found customer ID {customer_id} for email {email}")

        return jsonify({"customer_id": customer_id})
    except Exception as e:
        print(f"Error retrieving customer ID by email: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/get-customer-by-session", methods=["POST", "OPTIONS"])
def get_customer_by_session():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    data = request.get_json()
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    try:
        # Retrieve the session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)

        # Get the customer ID directly from the session
        customer_id = session.get("customer")

        if not customer_id:
            return jsonify({"error": "No customer ID found in session"}), 404

        print(f"Retrieved customer ID {customer_id} from session {session_id}")

        return jsonify({"customer_id": customer_id})
    except Exception as e:
        print(f"Error retrieving customer ID from session: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/get-customer-id", methods=["POST", "OPTIONS"])
def get_customer_id():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    data = request.get_json()
    user_uid = data.get("user_uid")

    if not user_uid:
        return jsonify({"error": "Missing user_uid"}), 400

    try:
        # Get the user's profile from Firestore
        profile_ref = fs_db.collection("profiles").document(user_uid)
        profile = profile_ref.get()

        if not profile.exists:
            return jsonify({"error": "User profile not found"}), 404

        profile_data = profile.to_dict()
        customer_id = profile_data.get("stripeCustomerId")

        if not customer_id:
            # Try to find the customer ID from Stripe
            email = profile_data.get("email")
            if email:
                customers = stripe.Customer.list(
                    limit=1,
                    email=email
                )

                if customers and customers.data:
                    customer_id = customers.data[0].id

                    # Update the user's profile with the customer ID
                    profile_ref.set({
                        "stripeCustomerId": customer_id
                    }, merge=True)

                    print(f"Found and updated customer ID for user {user_uid}: {customer_id}")
                else:
                    return jsonify({"error": "No Stripe customer found for this user"}), 404
            else:
                return jsonify({"error": "No email found for this user"}), 404

        return jsonify({"customer_id": customer_id})
    except Exception as e:
        print(f"Error retrieving customer ID: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/cancel-subscription-direct", methods=["POST", "OPTIONS"])
def cancel_subscription_direct():
    if request.method == "OPTIONS":
        return '', 200  # Preflight OK

    data = request.get_json()
    customer_id = data.get("customer_id")
    user_uid = data.get("user_uid")

    print(f"Received cancel subscription request: customer_id={customer_id}, user_uid={user_uid}")

    if not customer_id and not user_uid:
        return jsonify({"error": "Missing customer_id or user_uid"}), 400

    try:
        # If we only have user_uid, try to get the customer_id
        if not customer_id and user_uid:
            print(f"No customer_id provided, trying to get it from user profile: {user_uid}")
            profile_ref = fs_db.collection("profiles").document(user_uid)
            profile = profile_ref.get()

            if profile.exists:
                profile_data = profile.to_dict()
                customer_id = profile_data.get("stripeCustomerId")
                print(f"Found customer_id in profile: {customer_id}")

                if not customer_id:
                    print(f"No stripeCustomerId found in profile data: {profile_data}")

                    # Try to find the customer by email
                    if profile_data.get("email"):
                        email = profile_data.get("email")
                        print(f"Trying to find customer by email: {email}")

                        customers = stripe.Customer.list(
                            email=email,
                            limit=1
                        )

                        if customers and customers.data:
                            customer_id = customers.data[0].id
                            print(f"Found customer by email: {customer_id}")

                            # Update the profile with the customer ID
                            profile_ref.set({
                                "stripeCustomerId": customer_id
                            }, merge=True)
                        else:
                            print(f"No customer found for email: {email}")

                    if not customer_id:
                        return jsonify({"error": "No customer ID found for this user"}), 404
            else:
                print(f"User profile not found: {user_uid}")
                return jsonify({"error": "User profile not found"}), 404

        print(f"Looking up subscriptions for customer: {customer_id}")

        # Get all subscriptions for this customer
        subscriptions = stripe.Subscription.list(
            customer=customer_id,
            status="active",
            limit=10
        )

        print(f"Found active subscriptions: {[s.id for s in subscriptions.data]}")

        if not subscriptions or not subscriptions.data:
            print(f"No active subscriptions found for customer: {customer_id}")

            # Check if there are any subscriptions in other states
            all_subscriptions = stripe.Subscription.list(
                customer=customer_id,
                limit=10
            )

            print(f"All subscriptions for customer: {[s.id for s in all_subscriptions.data]}")

            # If there are no active subscriptions but the user's profile shows an active subscription,
            # update the profile to reflect the correct state
            if user_uid:
                profile_ref = fs_db.collection("profiles").document(user_uid)
                profile_ref.set({
                    "subscription": {
                        "active": False,
                        "plan": None,
                        "startedAt": None,
                        "endsAt": firestore.SERVER_TIMESTAMP,
                        "stripeSessionId": None
                    }
                }, merge=True)
                print(f"Updated user profile to inactive subscription state: {user_uid}")

                return jsonify({
                    "success": True,
                    "message": "No active subscriptions found, but user profile updated to reflect inactive state"
                })

            return jsonify({"error": "No active subscriptions found for this customer"}), 404

        # Cancel all active subscriptions
        cancelled_subscriptions = []
        for subscription in subscriptions.data:
            subscription_id = subscription.id
            print(f"Cancelling subscription: {subscription_id}")

            try:
                cancelled_subscription = stripe.Subscription.delete(subscription_id)
                print(f"Subscription cancelled: {cancelled_subscription.id}")
                cancelled_subscriptions.append(cancelled_subscription.id)
            except Exception as sub_err:
                print(f"Error cancelling subscription {subscription_id}: {str(sub_err)}")

        # Update the user's profile in Firebase
        if user_uid:
            print(f"Updating user profile: {user_uid}")
            profile_ref = fs_db.collection("profiles").document(user_uid)
            profile_ref.set({
                "subscription": {
                    "active": False,
                    "plan": None,
                    "startedAt": None,
                    "endsAt": firestore.SERVER_TIMESTAMP,
                    "stripeSessionId": None
                }
            }, merge=True)
            print(f"User profile updated: {user_uid}")

        return jsonify({
            "success": True,
            "message": "Subscription(s) cancelled successfully",
            "cancelled_subscriptions": cancelled_subscriptions
        })
    except Exception as e:
        print(f"Error cancelling subscription: {str(e)}")

        # If there was an error but we have a user_uid, still try to update the profile
        if user_uid:
            try:
                profile_ref = fs_db.collection("profiles").document(user_uid)
                profile_ref.set({
                    "subscription": {
                        "active": False,
                        "plan": None,
                        "startedAt": None,
                        "endsAt": firestore.SERVER_TIMESTAMP,
                        "stripeSessionId": None
                    }
                }, merge=True)
                print(f"User profile updated despite error: {user_uid}")

                return jsonify({
                    "success": True,
                    "message": "Error with Stripe but user profile updated to reflect inactive state",
                    "error": str(e)
                })
            except Exception as profile_err:
                print(f"Error updating user profile: {str(profile_err)}")

        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    # Get the raw payload as text to ensure it's not None
    payload = request.get_data(as_text=True)

    # Get the Stripe signature from headers
    sig_header = request.headers.get("stripe-signature")

    # Get the webhook secret from environment variables
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    # Check if webhook_secret is None
    if not webhook_secret:
        print("Error: STRIPE_WEBHOOK_SECRET is not set in environment variables")
        return jsonify({"error": "Webhook secret not configured"}), 500

    event = None
    try:
        # Ensure payload is properly encoded
        if isinstance(payload, str):
            payload_bytes = payload.encode('utf-8')
        else:
            payload_bytes = payload

        # Construct the event with proper error handling
        event = stripe.Webhook.construct_event(
            payload_bytes,
            sig_header,
            webhook_secret
        )
    except ValueError as e:
        # Invalid payload
        print(f"Webhook error (Invalid payload): {str(e)}")
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        print(f"Webhook error (Invalid signature): {str(e)}")
        return jsonify({"error": "Invalid signature"}), 400
    except Exception as e:
        # Other errors
        print(f"Webhook error (Unexpected): {str(e)}")
        return jsonify({"error": str(e)}), 400

    # Process the event
    try:
        print(f"Processing webhook event type: {event['type']}")

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            user_uid = session["metadata"].get("user_uid")
            customer_id = session.get("customer")
            plan = session["metadata"].get("plan")
            session_id = session.get("id")

            print(f"Processing checkout.session.completed: {session_id}")
            print(f"User UID: {user_uid}, Customer ID: {customer_id}, Plan: {plan}")

            if user_uid and customer_id and plan:
                profile_ref = fs_db.collection("profiles").document(user_uid)
                profile_ref.set({
                    "stripeCustomerId": customer_id,
                    "subscription": {
                        "active": True,
                        "plan": plan,
                        "startedAt": firestore.SERVER_TIMESTAMP,
                        "endsAt": None,
                        "stripeSessionId": session_id
                    }
                }, merge=True)
                print(f"Subscription successful for session: {session_id}")
                print(f"Updated user {user_uid} with customer ID {customer_id}")

        elif event["type"] == "customer.subscription.deleted":
            subscription = event["data"]["object"]
            customer_id = subscription.get("customer")

            print(f"Processing customer.subscription.deleted: {subscription.get('id')}")

            # Find the user by customer_id
            users = fs_db.collection("profiles").where("stripeCustomerId", "==", customer_id).stream()
            for user_doc in users:
                user_doc.reference.set({
                    "subscription": {
                        "active": False,
                        "plan": None,
                        "startedAt": None,
                        "endsAt": firestore.SERVER_TIMESTAMP
                    }
                }, merge=True)
                print(f"Subscription cancelled for user: {user_doc.id}")

        return "", 200
    except Exception as e:
        print(f"Error processing webhook event: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return "Stripe backend is running!"

if __name__ == "__main__":
    app.run(port=4242, debug=True)