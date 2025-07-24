#!/usr/bin/env python3
"""
Clean CV AI Processing Backend
Focused only on CV optimization and translation using Moonshot AI
"""

import os
import time
import base64
import requests
import io
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# PDF processing imports
try:
    import PyPDF2
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import inch
    PDF_PROCESSING_AVAILABLE = True
except ImportError:
    PDF_PROCESSING_AVAILABLE = False

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Configuration
KIMI_API_KEY = os.environ.get('KIMI_API_KEY')
KIMI_ENDPOINT = os.environ.get('KIMI_ENDPOINT', 'https://api.moonshot.cn/v1/chat/completions')
MOCK_MODE = os.environ.get('MOCK_MODE', 'false').lower() == 'true'

# Startup info
print("🚀 CV AI Backend Starting...")
print(f"🔑 API Key: {'✅ Set' if KIMI_API_KEY else '❌ Missing'}")
print(f"📊 Mock Mode: {'✅ Enabled' if MOCK_MODE else '❌ Disabled'}")
print(f"🤖 AI Processing: {'❌ Disabled' if MOCK_MODE else '✅ Enabled'}")
print(f"📄 PDF Processing: {'✅ Available' if PDF_PROCESSING_AVAILABLE else '❌ Install PyPDF2 & reportlab'}")

def get_timestamp():
    """Get current timestamp"""
    return int(time.time())

def call_moonshot_ai(prompt, max_tokens=4000):
    """Call Moonshot AI API with the given prompt"""
    if not KIMI_API_KEY:
        raise Exception("KIMI_API_KEY not set")
    
    headers = {
        'Authorization': f'Bearer {KIMI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "model": "moonshot-v1-8k",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens
    }
    
    response = requests.post(KIMI_ENDPOINT, headers=headers, json=payload, timeout=60)
    
    if response.status_code != 200:
        raise Exception(f"API Error {response.status_code}: {response.text}")
    
    result = response.json()
    
    if 'choices' not in result or not result['choices']:
        raise Exception("Invalid API response format")
    
    return result['choices'][0]['message']['content']

def extract_text_from_pdf_base64(base64_content):
    """Extract text from PDF base64 content"""
    if not PDF_PROCESSING_AVAILABLE:
        return "[PDF processing not available - install PyPDF2 and reportlab]"
    
    try:
        # Decode base64 to bytes
        pdf_bytes = base64.b64decode(base64_content)
        
        # Create PDF reader
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        
        # Extract text from all pages
        text_content = ""
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text_content += page.extract_text() + "\n"
        
        return text_content.strip()
        
    except Exception as e:
        raise Exception(f"Failed to extract text from PDF: {str(e)}")

def text_to_pdf_base64(text_content, filename="processed_cv.pdf"):
    """Convert text content to PDF base64"""
    if not PDF_PROCESSING_AVAILABLE:
        # Return original content if PDF processing not available
        return text_content
    
    try:
        # Create PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, 
                              rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        # Get styles
        styles = getSampleStyleSheet()
        story = []
        
        # Split text into paragraphs
        paragraphs = text_content.split('\n')
        
        for para_text in paragraphs:
            if para_text.strip():
                # Determine style based on content
                if para_text.isupper() or len(para_text) < 50:
                    # Likely a header
                    para = Paragraph(para_text, styles['Heading2'])
                else:
                    # Regular content
                    para = Paragraph(para_text, styles['Normal'])
                
                story.append(para)
                story.append(Spacer(1, 12))
        
        # Build PDF
        doc.build(story)
        
        # Get PDF bytes and encode to base64
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        return base64.b64encode(pdf_bytes).decode('utf-8')
        
    except Exception as e:
        raise Exception(f"Failed to convert text to PDF: {str(e)}")

def create_optimization_prompt(style):
    """Create optimization prompt based on style"""
    return f"""
You are a professional CV/resume optimization expert. I will provide you with a CV/resume content, and you need to optimize it significantly.

STYLE: {style}

Your task is to:

1. CONTENT OPTIMIZATION:
   - Rewrite bullet points to be more impactful and quantified
   - Enhance job descriptions with strong action verbs and measurable achievements
   - Add relevant keywords for ATS (Applicant Tracking Systems)
   - Remove weak or redundant content
   - Strengthen the professional summary/objective
   - Improve skills section with relevant technical and soft skills

2. LANGUAGE ENHANCEMENT:
   - Use powerful, professional language
   - Fix grammar and spelling issues
   - Improve clarity and conciseness
   - Use industry-appropriate terminology
   - Make achievements more compelling

3. STRUCTURE IMPROVEMENTS:
   - Organize information in logical order
   - Ensure consistent formatting
   - Optimize section headers
   - Improve readability and flow

4. STYLE-SPECIFIC GUIDELINES:
   - Modern: Contemporary language, clean structure, focus on achievements
   - Professional: Formal tone, traditional structure, conservative approach
   - Creative: Unique phrasing while maintaining professionalism
   - Classic: Timeless format, standard sections, proven structure

IMPORTANT: Return ONLY the optimized CV content. Do not include explanations, comments, or meta-text. The response should be the complete, ready-to-use optimized CV that is significantly better than the original.

Original CV content to optimize:

"""

def create_translation_prompt(target_language):
    """Create translation prompt for target language"""
    language_map = {
        'ar': 'Arabic', 'de': 'German', 'en': 'English', 'es': 'Spanish',
        'fr': 'French', 'it': 'Italian', 'ja': 'Japanese', 'pl': 'Polish',
        'pt': 'Portuguese', 'ru': 'Russian', 'zh': 'Chinese'
    }
    
    full_language = language_map.get(target_language, target_language)
    
    return f"""
You are a professional CV/resume translator specializing in career documents. I will provide you with a CV/resume, and you need to translate it to {full_language}.

TARGET LANGUAGE: {full_language}

Your task is to:

1. PROFESSIONAL TRANSLATION:
   - Translate all content accurately while maintaining professional tone
   - Use appropriate business/career terminology in {full_language}
   - Preserve the meaning and impact of achievements
   - Maintain professional formatting and structure

2. CULTURAL ADAPTATION:
   - Adapt content to {full_language} professional standards
   - Use culturally appropriate professional language
   - Adjust job titles to local market standards when appropriate
   - Consider regional business practices

3. QUALITY ASSURANCE:
   - Ensure grammatically correct {full_language}
   - Use professional vocabulary appropriate for CVs/resumes
   - Maintain consistency in terminology
   - Preserve professional impact and readability

4. STRUCTURE PRESERVATION:
   - Keep original formatting and layout structure
   - Translate section headers appropriately (Experience, Education, Skills, etc.)
   - Preserve dates, numbers, and proper nouns where appropriate
   - Maintain bullet points and visual hierarchy

IMPORTANT: Return ONLY the translated CV content in {full_language}. Do not include explanations, comments, or meta-text. The response should be the complete, professionally translated CV ready for use in {full_language}-speaking regions.

CV content to translate:

"""

@app.route('/')
def index():
    return f"""
    <h1>🤖 CV AI Processing Backend</h1>
    <p><strong>Status:</strong> ✅ Running</p>
    <p><strong>AI Processing:</strong> {'❌ Mock Mode' if MOCK_MODE else '✅ Enabled'}</p>
    <p><strong>API Key:</strong> {'✅ Set' if KIMI_API_KEY else '❌ Missing'}</p>
    <p><strong>PDF Processing:</strong> {'✅ Available' if PDF_PROCESSING_AVAILABLE else '❌ Missing Dependencies'}</p>
    
    <h3>📋 Available Endpoints:</h3>
    <ul>
        <li><code>POST /api/optimize-cv</code> - CV Optimization</li>
        <li><code>POST /api/translate-cv</code> - CV Translation</li>
        <li><code>GET /status</code> - Backend Status</li>
    </ul>
    
    <h3>⚙️ Configuration:</h3>
    <ul>
        <li>Set <code>KIMI_API_KEY</code> environment variable</li>
        <li>Set <code>MOCK_MODE=false</code> for real AI processing</li>
        <li>Install <code>pip install PyPDF2 reportlab</code> for PDF processing</li>
    </ul>
    """

@app.route('/status')
def status():
    return jsonify({
        'status': 'running',
        'ai_enabled': not MOCK_MODE and bool(KIMI_API_KEY),
        'mock_mode': MOCK_MODE,
        'has_api_key': bool(KIMI_API_KEY),
        'pdf_processing': PDF_PROCESSING_AVAILABLE,
        'endpoint': KIMI_ENDPOINT
    })

@app.route('/api/optimize-cv', methods=['POST'])
def optimize_cv():
    """Optimize CV using AI"""
    print("📝 Received CV optimization request")
    
    try:
        # Get file and parameters
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        style = request.form.get('style', 'modern')
        filename = file.filename
        
        print(f"📄 Processing: {filename} with {style} style")
        
        # Read and encode file
        file_content = file.read()
        file_base64 = base64.b64encode(file_content).decode('utf-8')
        
        if MOCK_MODE or not KIMI_API_KEY:
            print("⚠️ Mock mode - returning original file")
            processed_content = file_base64
            ai_response = f"Mock optimization completed for {style} style"
        else:
            print("🤖 Processing with AI...")
            
            # Extract text from PDF
            pdf_text = extract_text_from_pdf_base64(file_base64)
            print(f"📄 Extracted {len(pdf_text)} characters from PDF")
            
            # Create optimization prompt
            prompt = create_optimization_prompt(style) + pdf_text
            
            # Call AI API
            ai_response = call_moonshot_ai(prompt)
            print("✅ AI optimization completed")
            
            # Convert back to PDF
            processed_content = text_to_pdf_base64(ai_response, f"optimized-{filename}")
            print("📄 Generated optimized PDF")
        
        # Create response
        timestamp = get_timestamp()
        response_data = {
            'success': True,
            'filename': f'optimized-{filename}',
            'filedata': processed_content,
            'fileInfo': {
                'path': f'optimized/{timestamp}/{filename}',
                'download_url': f'data:application/pdf;base64,{processed_content}',
                'sha': f'opt-{timestamp}',
                'size': len(processed_content),
                'firestore_doc_id': f'opt-doc-{timestamp}',
                'ai_processed': not MOCK_MODE and bool(KIMI_API_KEY),
                'style': style,
                'pdf_processing': PDF_PROCESSING_AVAILABLE
            },
            'ai_response': ai_response if not MOCK_MODE else None,
            'mock_mode': MOCK_MODE
        }
        
        print("📤 Sending response")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/translate-cv', methods=['POST'])
def translate_cv():
    """Translate CV using AI"""
    print("🌐 Received CV translation request")
    
    try:
        # Get file and parameters
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        language = request.form.get('language', 'en')
        filename = file.filename
        
        print(f"📄 Processing: {filename} to {language}")
        
        # Read and encode file
        file_content = file.read()
        file_base64 = base64.b64encode(file_content).decode('utf-8')
        
        if MOCK_MODE or not KIMI_API_KEY:
            print("⚠️ Mock mode - returning original file")
            processed_content = file_base64
            ai_response = f"Mock translation to {language} completed"
        else:
            print("🤖 Processing with AI...")
            
            # Extract text from PDF
            pdf_text = extract_text_from_pdf_base64(file_base64)
            print(f"📄 Extracted {len(pdf_text)} characters from PDF")
            
            # Create translation prompt
            prompt = create_translation_prompt(language) + pdf_text
            
            # Call AI API
            ai_response = call_moonshot_ai(prompt)
            print("✅ AI translation completed")
            
            # Convert back to PDF
            processed_content = text_to_pdf_base64(ai_response, f"translated-{filename}")
            print("📄 Generated translated PDF")
        
        # Create response
        timestamp = get_timestamp()
        response_data = {
            'success': True,
            'filename': f'translated-{filename}',
            'filedata': processed_content,
            'fileInfo': {
                'path': f'translated/{timestamp}/{filename}',
                'download_url': f'data:application/pdf;base64,{processed_content}',
                'sha': f'trans-{timestamp}',
                'size': len(processed_content),
                'firestore_doc_id': f'trans-doc-{timestamp}',
                'ai_processed': not MOCK_MODE and bool(KIMI_API_KEY),
                'language': language,
                'pdf_processing': PDF_PROCESSING_AVAILABLE
            },
            'ai_response': ai_response if not MOCK_MODE else None,
            'mock_mode': MOCK_MODE
        }
        
        print("📤 Sending response")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    if not KIMI_API_KEY and not MOCK_MODE:
        print("⚠️ WARNING: No KIMI_API_KEY set and MOCK_MODE is disabled!")
        print("💡 Set KIMI_API_KEY or enable MOCK_MODE=true")
    
    if not PDF_PROCESSING_AVAILABLE:
        print("⚠️ WARNING: PDF processing not available!")
        print("💡 Install with: pip install PyPDF2 reportlab")
    
    print("🚀 Starting CV AI Backend on port 4242...")
    app.run(host='0.0.0.0', port=4242, debug=True)