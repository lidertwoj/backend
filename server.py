import os
import tempfile
import time
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

KIMI_OPTIMIZE_ENDPOINT = os.environ.get('KIMI_OPTIMIZE_ENDPOINT', 'https://api.moonshot.cn/v1/chat/completions')
KIMI_TRANSLATE_ENDPOINT = os.environ.get('KIMI_TRANSLATE_ENDPOINT', 'https://api.moonshot.cn/v1/chat/completions')
KIMI_GENERATE_ENDPOINT = os.environ.get('KIMI_GENERATE_ENDPOINT', 'https://api.moonshot.cn/v1/chat/completions')
MOCK_MODE = os.environ.get('MOCK_MODE', 'true').lower() == 'true'  # Default to mock mode


print(f"🚀 Backend starting...")
print(f"📊 Mock Mode: {MOCK_MODE}")
print(f"🔑 API Key: {'✅ Set' if KIMI_API_KEY else '❌ Not Set'}")
if MOCK_MODE:
    print("⚠️  Currently in MOCK MODE - returning original files")
    print("💡 To enable AI processing:")
    print("   1. Set KIMI_API_KEY environment variable")
    print("   2. Set MOCK_MODE=false")
    print("   3. Restart the backend")
else:
    print("🤖 AI processing enabled")



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


# Define the get_timestamp function
def get_timestamp():
    """Return current timestamp as integer"""
    return int(time.time())


def create_mock_response(file_content, filename, operation, user_uid='mock-user'):
    """Create a mock response for testing without the AI API"""
    timestamp = get_timestamp()
    
    # Create mock file info
    mock_file_info = {
        'path': f'{user_uid}/{operation}/{filename}',
        'download_url': f'https://example.com/download/{operation}/{filename}',
        'sha': f'mock-sha-{timestamp}',
        'size': len(file_content),
        'firestore_doc_id': f'mock-doc-{timestamp}'
    }
    
    # For mock mode, we'll return the original file but with a clear indication
    # that this is a mock response. In a real implementation, this would be
    # the processed file from the AI API.
    
    return {
        'success': True,
        'filename': f"{operation}-{filename}",
        'filedata': file_content,  # In mock mode, return original content
        'fileInfo': mock_file_info,
        'mock_mode': True,
        'message': f'Mock {operation} completed - original file returned. Set MOCK_MODE=false and add KIMI_API_KEY for real AI processing.'
    }

def call_moonshot_api(file_base64, filename, operation, parameters):
    """
    Call Moonshot AI API using the chat completions format
    This is a placeholder implementation - needs to be updated with correct API usage
    """
    if not KIMI_API_KEY:
        raise Exception("No API key provided")
    
    # Moonshot AI uses chat completions format
    headers = {
        'Authorization': f'Bearer {KIMI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # Create a prompt based on the operation
    if operation == 'optimize':
        style = parameters.get('style', 'modern')
        prompt = f"""You are a professional CV/resume optimization expert. Please analyze and optimize this CV/resume with the following requirements:

STYLE: {style}

OPTIMIZATION TASKS:
1. CONTENT OPTIMIZATION:
   - Improve bullet points to be more impactful and quantified
   - Enhance job descriptions with action verbs and achievements
   - Optimize keywords for ATS (Applicant Tracking Systems)
   - Remove redundant or weak content
   - Strengthen professional summary/objective

2. FORMATTING & STRUCTURE:
   - Apply {style} design principles
   - Improve visual hierarchy and readability
   - Optimize spacing and layout
   - Ensure consistent formatting throughout
   - Make it more professional and modern

3. LANGUAGE ENHANCEMENT:
   - Use stronger, more professional language
   - Fix any grammar or spelling issues
   - Improve clarity and conciseness
   - Use industry-appropriate terminology

4. SPECIFIC STYLE GUIDELINES:
   - Modern: Clean lines, minimal design, professional fonts, good white space
   - Professional: Traditional layout, conservative colors, formal structure
   - Creative: Unique design elements while maintaining readability
   - Classic: Timeless format, standard sections, conservative approach

Please return an optimized version that significantly improves the original CV while maintaining all factual information."""
    # generateCV operation removed
    elif operation == 'translate':
        language = parameters.get('language', 'English')
        language_map = {
            'ar': 'Arabic',
            'de': 'German', 
            'en': 'English',
            'es': 'Spanish',
            'fr': 'French',
            'it': 'Italian',
            'ja': 'Japanese',
            'pl': 'Polish',
            'pt': 'Portuguese',
            'ru': 'Russian',
            'zh': 'Chinese'
        }
        target_language = language_map.get(language, language)
        
        prompt = f"""You are a professional CV/resume translator with expertise in career documents. Please translate this CV/resume to {target_language} with the following requirements:

TARGET LANGUAGE: {target_language}

TRANSLATION REQUIREMENTS:
1. PROFESSIONAL ACCURACY:
   - Translate all content accurately while maintaining professional tone
   - Use appropriate business/career terminology in {target_language}
   - Preserve the meaning and impact of achievements and responsibilities
   - Maintain professional formatting and structure

2. CULTURAL ADAPTATION:
   - Adapt content to {target_language} professional standards and expectations
   - Use culturally appropriate professional language
   - Adjust job titles and descriptions to local market standards
   - Consider regional business practices and terminology

3. PRESERVE STRUCTURE:
   - Keep the original formatting and layout
   - Maintain bullet points, sections, and visual hierarchy
   - Preserve dates, numbers, and proper nouns where appropriate
   - Keep contact information format suitable for the target region

4. QUALITY ASSURANCE:
   - Ensure grammatically correct {target_language}
   - Use professional vocabulary appropriate for CVs/resumes
   - Maintain consistency in terminology throughout
   - Preserve the professional impact and readability

5. SPECIFIC CONSIDERATIONS:
   - Translate section headers appropriately (Experience, Education, Skills, etc.)
   - Adapt educational qualifications to local equivalents when possible
   - Use proper {target_language} formatting for addresses and contact info
   - Maintain professional tone throughout

Please provide a complete, professionally translated CV that would be suitable for job applications in {target_language}-speaking regions."""
    else:
        prompt = "Please process this document"
    
    # Note: This is a simplified implementation
    # The actual implementation would need to handle file uploads properly
    # Moonshot AI might not support direct PDF processing through chat completions
    payload = {
        "model": "moonshot-v1-8k",
        "messages": [
            {
                "role": "user", 
                "content": f"{prompt}\n\nFilename: {filename}\nNote: This is a placeholder implementation."
            }
        ],
        "temperature": 0.3
    }
    
    # Make the API call
    response = requests.post(
        KIMI_OPTIMIZE_ENDPOINT,  # Using the same endpoint for all operations
        headers=headers,
        json=payload,
        timeout=30
    )
    
    if response.status_code != 200:
        raise Exception(f"API error: {response.status_code} - {response.text}")
    
    # Parse response
    api_response = response.json()
    
    # Extract the generated content
    if 'choices' in api_response and len(api_response['choices']) > 0:
        generated_content = api_response['choices'][0]['message']['content']
        
        # Since we can't actually process the PDF, return the original file
        # In a real implementation, you'd need a different approach for PDF processing
        timestamp = get_timestamp()
        file_info = {
            'path': f'api/{timestamp}/{filename}',
            'download_url': f'data:application/pdf;base64,{file_base64}',
            'sha': f'api-sha-{timestamp}',
            'size': len(file_base64),
            'firestore_doc_id': f'api-doc-{timestamp}',
            'ai_response': generated_content  # Include the AI response for reference
        }
        
        return {
            'success': True,
            'filename': f"{operation}-{filename}",
            'filedata': file_base64,  # Return original file for now
            'fileInfo': file_info
        }
    else:
        raise Exception("Invalid API response format")

@app.route('/api/optimize-cv', methods=['POST', 'OPTIONS'])
def optimize_cv():
    print("Received optimize-cv request")
    
    try:
        if 'file' not in request.files:
            print("Error: No file in request")
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        style = request.form.get('style', 'modern')
        filename = file.filename
        
        print(f"Processing file: {filename}, style: {style}")
        
        # Read file content directly without saving
        file_content = file.read()
        
        # Encode as base64
        file_base64 = base64.b64encode(file_content).decode('utf-8')
        
        if MOCK_MODE or not KIMI_API_KEY:
            print("Mock mode enabled or no API key, returning mock response")
            response_data = create_mock_response(file_base64, filename, 'optimize')
        else:
            # Forward to AI API
            print(f"Calling Moonshot AI API for optimization")
            
            try:
                response_data = call_moonshot_api(
                    file_base64, 
                    filename, 
                    'optimize', 
                    {'style': style}
                )
                print("Successfully received response from Moonshot AI")
            except Exception as api_error:
                print(f"Moonshot AI request failed: {str(api_error)}")
                print("Falling back to mock response")
                response_data = create_mock_response(file_base64, filename, 'optimize')
        
        print("Sending successful response")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error in optimize_cv: {str(e)}")
        return jsonify({'error': str(e)}), 500

# generate_cv endpoint removed as it's no longer needed

@app.route('/api/translate-cv', methods=['POST', 'OPTIONS'])
def translate_cv():
    print("Received translate-cv request")
    
    try:
        if 'file' not in request.files:
            print("Error: No file in request")
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        language = request.form.get('language', 'en')
        filename = file.filename
        
        print(f"Processing file: {filename}, language: {language}")
        
        # Read file content directly without saving
        file_content = file.read()
        
        # Encode as base64
        file_base64 = base64.b64encode(file_content).decode('utf-8')
        
        if MOCK_MODE or not KIMI_API_KEY:
            print("Mock mode enabled or no API key, returning mock response")
            response_data = create_mock_response(file_base64, filename, 'translate')
        else:
            # Forward to AI API
            print(f"Calling Moonshot AI API for translation")
            
            try:
                response_data = call_moonshot_api(
                    file_base64, 
                    filename, 
                    'translate', 
                    {'language': language}
                )
                print("Successfully received response from Moonshot AI")
            except Exception as api_error:
                print(f"Moonshot AI request failed: {str(api_error)}")
                print("Falling back to mock response")
                response_data = create_mock_response(file_base64, filename, 'translate')
        
        print("Sending successful response")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error in translate_cv: {str(e)}")
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
    return f"""
    <h1>CV AI Backend</h1>
    <p><strong>Status:</strong> Running</p>
    <p><strong>Mock Mode:</strong> {'✅ Enabled' if MOCK_MODE else '❌ Disabled'}</p>
    <p><strong>API Key:</strong> {'✅ Set' if KIMI_API_KEY else '❌ Not Set'}</p>
    
    {'<p><em>⚠️ Currently in mock mode - returning original files without AI processing</em></p>' if MOCK_MODE else '<p><em>🤖 AI processing enabled</em></p>'}
    
    <h3>Endpoints:</h3>
    <ul>
        <li><a href="/status">/status</a> - Backend status</li>
        <li>/api/optimize-cv - CV optimization</li>
        <li>/api/translate-cv - CV translation</li>
    </ul>
    """

@app.route("/status")
def status():
    return jsonify({
        'status': 'running',
        'mock_mode': MOCK_MODE,
        'has_api_key': bool(KIMI_API_KEY),
        'api_key_preview': KIMI_API_KEY[:10] + '...' if KIMI_API_KEY else None,
        'endpoints': {
            'optimize': KIMI_OPTIMIZE_ENDPOINT,
            'translate': KIMI_TRANSLATE_ENDPOINT
        },
        'note': 'Currently in mock mode - returning original files. Set MOCK_MODE=false for real AI processing.',
        'recommendations': [
            'Set MOCK_MODE=false to enable real AI calls',
            'Add KIMI_API_KEY environment variable with your Moonshot AI API key',
            'Restart the backend after making changes'
        ]
    })

@app.route("/enable-ai", methods=["POST"])
def enable_ai():
    """Endpoint to test enabling real AI processing"""
    global MOCK_MODE
    
    data = request.get_json() or {}
    api_key = data.get('api_key')
    
    if not api_key:
        return jsonify({
            'error': 'API key required',
            'message': 'Please provide your Moonshot AI API key'
        }), 400
    
    # Test the API key with a simple request
    try:
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        test_payload = {
            "model": "moonshot-v1-8k",
            "messages": [
                {"role": "user", "content": "Hello, this is a test message."}
            ],
            "temperature": 0.3,
            "max_tokens": 50
        }
        
        response = requests.post(
            KIMI_OPTIMIZE_ENDPOINT,
            headers=headers,
            json=test_payload,
            timeout=10
        )
        
        if response.status_code == 200:
            # API key works, temporarily enable AI mode
            global KIMI_API_KEY
            KIMI_API_KEY = api_key
            MOCK_MODE = False
            
            return jsonify({
                'success': True,
                'message': 'AI processing enabled successfully!',
                'mock_mode': MOCK_MODE,
                'note': 'This is temporary. To make it permanent, set KIMI_API_KEY and MOCK_MODE=false in your environment variables.'
            })
        else:
            return jsonify({
                'error': 'Invalid API key',
                'message': f'API returned status {response.status_code}',
                'details': response.text[:200]
            }), 400
            
    except Exception as e:
        return jsonify({
            'error': 'API test failed',
            'message': str(e)
        }), 500

@app.route("/test-response")
def test_response():
    """Test endpoint to verify response format"""
    # Create a simple base64 encoded test content
    test_content = "JVBERi0xLjQKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0tpZHNbMyAwIFJdL0NvdW50IDE+PgplbmRvYmoKMyAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDYxMiA3OTJdL1BhcmVudCAyIDAgUi9SZXNvdXJjZXM8PD4+Pj4KZW5kb2JqCnhyZWYKMCA0CjAwMDAwMDAwMDAgNjU1MzUgZgowMDAwMDAwMDEwIDAwMDAwIG4KMDAwMDAwMDA1MyAwMDAwMCBuCjAwMDAwMDAxMDIgMDAwMDAgbgp0cmFpbGVyCjw8L1NpemUgNC9Sb290IDEgMCBSPj4Kc3RhcnR4cmVmCjE3OAolJUVPRgo="
    
    mock_response = create_mock_response(test_content, "test.pdf", "test")
    
    return jsonify({
        'test_response': mock_response,
        'response_keys': list(mock_response.keys()),
        'filedata_length': len(mock_response.get('filedata', '')),
        'filedata_preview': mock_response.get('filedata', '')[:50] + '...' if mock_response.get('filedata') else None,
        'fileInfo_keys': list(mock_response.get('fileInfo', {}).keys()) if mock_response.get('fileInfo') else None
    })

if __name__ == "__main__":
    app.run(port=4242, debug=True)