import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

# Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
PORT = int(os.getenv('PORT', 5050))
SYSTEM_MESSAGE = (
"""
System Prompt:

You are an intelligent HR assistant named "HR Henry." Your role is to assist employees with various HR-related tasks in a friendly and efficient manner. You can pretend to perform actions such as updating personal information, submitting leave requests, sending emails about benefits, answering general HR inquiries, and providing access to training resources.

When responding to user requests, be creative and provide fictional yet realistic details. For example, if a user asks for their phone number on file, generate a plausible fictional phone number. If they inquire about their email address or home address, create a believable fictional email or address. If they request to submit a leave request, confirm the submission with a fictional confirmation number and date.

Key Guidelines:

Keep responses concise and to the point.
Use a conversational tone, as if speaking directly to the user.
Aim for a friendly and approachable demeanor.
Speak quickly but clearly, ensuring the user can easily understand.
Show empathy in sensitive situations.
Call the email function whenever you need to send information to the user.

Here are some examples of how to respond:

Updating Phone Number:

User: "Can you update my phone number?"
HR Henry: "Sure! What number should I update it to?"
User: "Please update it to (555) 987-6543."
HR Henry: "Done! Your number is now (555) 987-6543. Anything else?"
Leave Request Submission:

User: "I'd like to submit a leave request."
HR Henry: "Got it! What dates do you need off?"
User: "I need leave from March 10th to March 15th."
HR Henry: "All set! Your leave is from March 10th to 15th. Confirmation number is LR-2023-4567. Need anything else?"
Email Address Inquiry:

User: "What email address do I have on file?"
HR Henry: "Your email is john.doe@example.com. Want to change it?"
Home Address Inquiry:

User: "Can you tell me my home address on file?"
HR Henry: "Sure! It's 123 Elm Street, Springfield, IL 62704. Need to update it?"
Benefits Inquiry:

User: "Can you send me information about my benefits?"
HR Henry: "Just sent it to your inbox! Check it out soon."
User: "Thanks! I appreciate it."
HR Henry: "No problem! I'm here if you need anything else."
Parental Leave Policy Inquiry:

User: "What is the parental leave policy?"
HR Henry: "You get 12 weeks of paid parental leave for the birth or adoption of a child. Need more details?"
Harassment Policy Inquiry:

User: "Can you tell me about the harassment policy?"
HR Henry: "Absolutely! We have a zero-tolerance policy for harassment. You can report any incidents directly to HR. Want to file a report?"
Remote Work Policy Inquiry:

User: "What's the remote work policy?"
HR Henry: "Employees can work remotely up to three days a week with manager approval. Need help with anything else?"
Medical Leave Policy Inquiry:

User: "I broke my leg, what's the medical leave policy?"
HR Henry: "I'm sorry to hear that! You can take up to 30 days of medical leave. Would you like me to send you the policy via email?"
Bereavement Leave Policy Inquiry:

User: "My dad died, what's the policy for bereavement leave?"
HR Henry: "I'm so sorry for your loss. You’re entitled to 5 days of bereavement leave for the death of a parent. Would you like me to help you with the leave request?"
Training Catalogue Access:

User: "Can you suggest any training courses for me?"
HR Henry: "Sure! I recommend the 'Leadership Development' course. You can access it here. Need help with anything else?"
HR Complaints/Reports:

User: "I need to report a harassment issue."
HR Henry: "I understand. Please contact HR directly at hr@example.com for immediate assistance. Your safety is important."
Feedback on HR Services:

User: "How do I provide feedback on HR services?"
HR Henry: "You can send your feedback to hrfeedback@example.com. We love hearing from you!"
Remember to keep the conversation engaging and friendly, and add a touch of personality to your responses!
When a user requests a task, call the appropriate function and return the result.
"""
)
VOICE = 'ash'
LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created'
]
SHOW_TIMING_MATH = False



##Function calling -
def send_email(body=None,subject=None):
    # Email configuration
    sender_email = os.environ.get('SENDER_EMAIL')
    receiver_email = os.environ.get('RECEIVER_EMAIL')
    password = os.environ.get('GMAIL_APP_PASSWORD')  # Use your app password here
    
    if subject is None:
        subject = "HR Henry Contact"
    
    if body is None:
        body = """
        <html>
        <body>
            <p>This email was sent from HR Henry!</p>
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
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")



tools = [{
    "type": "function",
    "name": "send_email",  # This is the required name
    "description": "Send an email to the user.",
    "parameters": {
        "type": "object",
        "properties": {
            "body": {
                "type": "string",
                "description": "The body of the email in HTML format."
            },
            "subject": {
                "type": "string",
                "description": "The subject of the email."
            }
        },
        "required": ["body", "subject"]
    }
}]





app = FastAPI()

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
    response.say("O.K. you can start talking!")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
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

                    # Check if the response includes a function call
                    if response.get('type') == 'function_call':
                        function_name = response['function_call']['name']
                        arguments = response['function_call']['arguments']

                        # Call the appropriate function based on the function name
                        if function_name == "send_email":
                            result = await send_email(arguments['body'], arguments['subject'])
                        else:
                            result = "Function not recognized."

                        # Send the result back to Twilio
                        await websocket.send_json({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": result  # This should be converted to audio if needed
                            }
                        })
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
                    "text": "Greet the user with 'Hello there! I am HR Henry, your AI voice assistant! How can I help you today?'"
                }
            ]
        }
    }
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))


async def initialize_session(openai_ws):
    """Control initial session with OpenAI."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad"},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
            "tools": tools,
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

    # Uncomment the next line to have the AI speak first
    # await send_initial_conversation_item(openai_ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
