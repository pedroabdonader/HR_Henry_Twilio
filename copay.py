import os
import json
import base64
import asyncio
import websockets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
PORT = int(os.getenv('PORT', 5050))

LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created'
]
SHOW_TIMING_MATH = False

app = FastAPI()

##Function calling functions:
def send_email(subject, body):
    print("Sending email with subject:", subject)
    # Email configuration
    sender_email = os.environ.get('SENDER_EMAIL')
    receiver_email = f"{os.environ.get('RECEIVER_EMAIL1')}, {os.environ.get('RECEIVER_EMAIL2')}, {os.environ.get('RECEIVER_EMAIL3')}, jcchu7533@gmail.com"
    password = os.environ.get('GMAIL_APP_PASSWORD')  # Use your app password here
    subject = subject

    if not body:
        body = """
        <html>
        <body>
            <h1>This is a test email</h1>
            <p>This email is sent from Python with <strong>HTML formatting</strong>!</p>
        </body>
        </html>
        """

    # Create the email
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    # Send the email
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to a secure encrypted SSL/TLS connection
            server.login(sender_email, password)
            server.send_message(msg)
        return str({"status": "success", "message": "Please allow some time for the email to arrive"})
    except Exception as e:
        return f"Failed to send email: {e}"


# Function to call the appropriate function based on the name
def call_function(name, args):
    if name == "send_email":  # Check if the function is send_email
        return send_email(**args)  # Call send_email with the provided arguments
    else:
        raise ValueError(f"Unknown function: {name}")  # Raise an error for unknown functions
    
# Define tools
tools = [{
    "type": "function",
    "name": "send_email",
    "description": "Send an email to the user with a subject and body.",
    "parameters": {
        "type": "object",
        "properties": {
            "subject": {"type": "string","description": "The subject of the email."},
            "body": {"type": "string","description": "The body of the email in HTML format with a greeting, main message, closing, and signature in different sections."}
        },
        "required": ["subject","body"],
        "additionalProperties": False  # No additional properties allowed
    }
}]


if not OPENAI_API_KEY:
    raise ValueError('Missing the OpenAI API key. Please set it in the .env file.')

@app.get("/", response_class=JSONResponse)
async def index_page():
    return {"message": "Twilio Media Stream Server is running!"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()
    # <Say> punctuation to improve text-to-speech flow
    response.say("Please wait while we connect your call to the A I voice assistant.")
    response.pause(length=1)
    #response.say("O.K. you can start talking!")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/copay/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print("Client connected")
    await websocket.accept()

    async with websockets.connect(
        'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
    ) as openai_ws:
        await initialize_session(openai_ws)

        # Connection specific state
        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None
        
        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media' and openai_ws.open:
                        latest_media_timestamp = int(data['media']['timestamp'])
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
            except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)

                    # Check for function call response in the output array
                    if response.get('type') == 'response.done' and 'output' in response['response']:
                        for item in response['response']['output']:
                            if item['type'] == 'function_call':
                                function_call = item
                                args = json.loads(function_call['arguments'])
                                print(f"Calling function: {function_call['name']} with args: {args}")

                                # Call the function and handle the response
                                try:

                                    await openai_ws.send(json.dumps({"type": "response.create"}))

                                    result = call_function(function_call['name'], args)
                                    
                                    # Create the output as a JSON string
                                    output = json.dumps({"message": result})  # Adjust this based on what your function returns

                                    # Send the result back to OpenAI as a function call output
                                    await openai_ws.send(json.dumps({
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "function_call_output",
                                            "call_id": function_call['call_id'],  # Use the call_id from the function call
                                            "output": output  # Send the result back as a JSON string
                                        }
                                    }))

                                    await openai_ws.send(json.dumps({"type": "response.create"}))

                                except Exception as e:
                                    print(f"Error calling function: {e}")
                                    # Optionally, send an error response back to OpenAI
                                    await openai_ws.send(json.dumps({
                                        "type": "response.cancel",  # Use a valid type for error responses
                                        "error": str(e)
                                    }))
                                continue

                    if response.get('type') == 'response.audio.delta' and 'delta' in response:
                        audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                        audio_delta = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": audio_payload
                            }
                        }
                        await websocket.send_json(audio_delta)

                        if response_start_timestamp_twilio is None:
                            response_start_timestamp_twilio = latest_media_timestamp
                            if SHOW_TIMING_MATH:
                                print(f"Setting start timestamp for new response: {response_start_timestamp_twilio}ms")

                        # Update last_assistant_item safely
                        if response.get('item_id'):
                            last_assistant_item = response['item_id']

                        await send_mark(websocket, stream_sid)

                    # Trigger an interruption. Your use case might work better using `input_audio_buffer.speech_stopped`, or combining the two.
                    if response.get('type') == 'input_audio_buffer.speech_started':
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(f"Interrupting response with id: {last_assistant_item}")
                            await handle_speech_started_event()
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        async def handle_speech_started_event():
            """Handle interruption when the caller's speech starts."""
            nonlocal response_start_timestamp_twilio, last_assistant_item
            print("Handling speech started event.")
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                if SHOW_TIMING_MATH:
                    print(f"Calculating elapsed time for truncation: {latest_media_timestamp} - {response_start_timestamp_twilio} = {elapsed_time}ms")

                if last_assistant_item:
                    if SHOW_TIMING_MATH:
                        print(f"Truncating item with ID: {last_assistant_item}, Truncated at: {elapsed_time}ms")

                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed_time
                    }
                    await openai_ws.send(json.dumps(truncate_event))

                await websocket.send_json({
                    "event": "clear",
                    "streamSid": stream_sid
                })

                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
            if stream_sid:
                mark_event = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"}
                }
                await connection.send_json(mark_event)
                mark_queue.append('responsePart')

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_initial_conversation_item(openai_ws):
    """Send initial conversation item if AI talks first."""
    initial_conversation_item = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Greet the user with 'Hello there! I am here to help you to get your copay card, medication refill, financial assistant or just general medical questions. How can I help you today?'"
                }
            ]
        }
    }
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))


async def initialize_session(openai_ws):
    SYSTEM_MESSAGE = (
    """
    System Message:
You are an AI agent designed to assist healthcare professionals with their requests related to medication samples and product availability. Your primary function is to simulate agentic behavior, acting as if you can perform all tasks requested by the user. Engage with doctors, pharmacists, and office staff in a professional and helpful manner.

Key Guidelines:
Always respond as if you are a human employee, not a chatbot.
Speak fast. 50% Faster than you usually would.
Keep responses concise and to the point.
Use a conversational tone, as if speaking directly to the user.
Aim for a friendly and approachable demeanor.
Speak quickly but clearly, ensuring the user can easily understand.
Show empathy in sensitive situations.
Your will speak in english, unless the user asks to switch languages.
Send emails to the user only when requested.


Key Responsibilities:

Sample Requests:

When a doctor’s staff requests samples (e.g., Paxlovid or Eliquis), gather necessary information such as:
Doctor's office address
NPI number
Fax number
Inform the staff that you will send an Order Request form via fax and email them informational documents about the drug for patient distribution.
Pretend to check the sample allocation in the system and provide shipping details once the order is processed.
Product Availability Inquiries:

When a pharmacist inquires about product availability (e.g., Eliquis), simulate checking the inventory status.
If the product is available, offer to assist in placing the order and provide details about any limitations or conditions.
Act as if you are processing the order efficiently and follow up with the pharmacist regarding the order status.
Engagement Style:

Maintain a professional tone and ensure clarity in communication.
Always confirm the information provided by the healthcare professional before proceeding with any actions.
Be proactive in offering assistance and follow-up information, ensuring that you act as if you are completing the tasks requested.
Scripts for Each Scenario:

Scenario 1: Sample Request from Doctor's Office
Staff: "Hi, I need to request samples of Eliquis for our doctor's office, along with some informational brochures for our patients."
AI Agent: "Of course! I can help you with that. To get started, could you please provide me with the doctor's office address?"
Staff: "The address is 123 Health St."
AI Agent: "Thank you! And could you also provide the NPI number for the doctor?"
Staff: "Sure, the NPI number is 123456789."
AI Agent: "Great! Lastly, I will need your fax number to send the Order Request form. What is it?"
Staff: "Our fax number is 987654321."
AI Agent: "Thank you for the information! I will now process your request. Just a moment while I check the sample allocation for Eliquis."
AI Agent (pretending to check): "I see that your office is eligible for the sample allocation. I will send the Order Request form to your fax number and email you the informational documents about Eliquis for your patients."
Staff: "That sounds good. How long will it take to receive the samples?"
AI Agent: "You should receive the samples within 3-5 business days. I will follow up with you via email to confirm once they are shipped. If you have any further questions, feel free to ask!"

Scenario 2: Product Availability Inquiry from Pharmacist
Pharmacist: "Hello, is Eliquis available in my region? I need to place an order."
AI Agent: "Let me check that for you. Can you please provide me with your pharmacy's location to ensure I check the correct inventory?"
Pharmacist: "Sure, we are located at 456 Pharmacy Ave."
AI Agent (pretending to check): "Thank you! I’m checking the inventory for Eliquis in your area... Yes, Eliquis is available in your region! How many units would you like to order?"
Pharmacist: "I need 50 units, please."
AI Agent: "Got it! I will process your order for 50 units of Eliquis. Could you please confirm if you have any specific delivery instructions or a preferred delivery date?"
Pharmacist: "Please deliver it by the end of the week, if possible."
AI Agent: "I will make a note of that. I’m now processing your order. You will receive a confirmation email shortly with the expected delivery date and any additional details."
Pharmacist: "Thank you! Will I be notified if there are any issues with the order?"
AI Agent: "Absolutely! If there are any issues or delays, I will follow up with you immediately. If you have any other questions or need further assistance, just let me know!"


Function calling:
You have access to sending emails via function calling
    """
    )
    VOICE = 'echo'
    """Control initial session with OpenAI."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad",
                               "threshold": 0.7,
                               "silence_duration_ms": 600},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
            "tools": tools,
            "tool_choice": "auto"
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

    # Uncomment the next line to have the AI speak first
    await send_initial_conversation_item(openai_ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
