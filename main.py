from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse
from hr import app as hr_app
from copay import app as copay_app

app = FastAPI(__name__)

app.mount('/hr', hr_app)
app.mount('/copay', copay_app)


@app.post('/incoming-call')
async def voice(request: Request):
    """Handle incoming voice calls."""
    response = VoiceResponse()
    response.dial("+18665703759")
    return Response(str(response), mimetype='text/xml')


if __name__ == '__main__':
    app.run()
