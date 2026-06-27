import io
import requests
import os
import json
from flask import Flask, jsonify, request, send_file
from dotenv import load_dotenv
from flask_cors import CORS
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.core.credentials import AzureKeyCredential
from langchain.chat_models import AzureChatOpenAI
from langchain.schema import HumanMessage
import azure.cognitiveservices.speech as speech_sdk

load_dotenv()

# Load Azure Credentials
image_key = os.getenv('VISION_KEY')
image_endpoint = os.getenv('VISION_ENDPOINT')

gpt_key = os.getenv('AZURE_OPENAI_KEY')
gpt_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
gpt_deployment_name = os.getenv('AZURE_OPENAI_DEPLOYMENT_NAME')

audio_key = os.getenv('AUDIO_KEY') 
audio_location = os.getenv('AUDIO_LOCATION')

app = Flask(__name__)
CORS(app)

# Initialize Azure Vision OCR Client
image_analysis_client = ImageAnalysisClient(
    endpoint=image_endpoint,
    credential=AzureKeyCredential(image_key)
)

# Initialize Azure OpenAI Chat Model
azure_chat_openai = AzureChatOpenAI(
    openai_api_base=gpt_endpoint,
    openai_api_key=gpt_key,
    deployment_name=gpt_deployment_name,
    openai_api_type='azure',
    openai_api_version='2023-05-15'
)

def convert_to_grams(nutritional_breakdown, nutritionalPerSize, servingSize):
    processed_data = []
    print("hello", nutritional_breakdown)
    factor = float(servingSize.replace("g", "")) / float(nutritionalPerSize.replace("g", ""))
    # factor = 1
    for nutrition in nutritional_breakdown:
        label, value = nutrition["label"], nutrition["value"]
        if isinstance(value, str) and value:
            value = value.lower().replace(" ", "")  # Normalize text
        
            # Extract numerical value
            num_value = float(''.join(filter(lambda x: x.isdigit() or x == '.', value)))

            # Convert based on units
            if "mg" in value:
                final_value = round(num_value * factor / 1000, 1)  # mg to g
            elif "µg" in value or "mcg" in value:
                final_value = round(num_value * factor / 1000000, 6) # µg/mcg to g
            elif "g" in value:
                final_value = round(num_value * factor, 1) # Already in g
        else:
            final_value = value  # Keep unchanged if not a string
        
        if final_value != 0:
            processed_data.append({
                "label": label,
                "value": final_value
            })

    return processed_data

@app.route('/synthesize', methods=['POST'])
def synthesize_audio():
    text = request.json['speech']
    speech_client = speech_sdk.SpeechConfig(subscription=audio_key, region=audio_location)
    audio_config = speech_sdk.audio.AudioOutputConfig(filename='output.wav')

    speech_client.speech_synthesis_voice_name = 'en-GB-RyanNeural'
    speech_synthesizer = speech_sdk.SpeechSynthesizer(speech_config=speech_client, audio_config=audio_config)

    speak = speech_synthesizer.speak_text_async(text).get()

    if speak.reason == speech_sdk.ResultReason.SynthesizingAudioCompleted:
        print("hello world")
        return send_file("output.wav", mimetype="audio/wav", as_attachment=True)
    else:
        print("hello")
        return jsonify({"error": "Speech synthesis failed"}), 500

@app.route('/upload', methods=['POST'])
def upload_image():
    # return jsonify({"formatted_data": "success"})
    if 'image' not in request.files:
        return jsonify({"error": "No image provided"}), 400

    image = request.files['image']
    gender = request.form.get('gender')
    age = request.form.get('age')
    allergic = request.form.get('allergic')
    diabetic = request.form.get('diabetic')
    hypertension = request.form.get('hypertension')
    cholesterol = request.form.get('cholesterol')
    diet = request.form.get('diet')
    allergic = allergic.replace(" ", "").split(",")
    diet = diet.replace(" ", "").split(",")

    try:
        # Read image bytes
        image_bytes = image.read()

        # Perform OCR using Azure SDK
        result = image_analysis_client.analyze(
            image_data=image_bytes,
            visual_features=["Read"]
        )

        # Extract text from OCR result
        extracted_text = []
        if result.read and result.read.blocks:
            for block in result.read.blocks:
                extracted_text.append(" ".join([line.text for line in block.lines]))

        extracted_text_str = "\n".join(extracted_text)

        # Send extracted text to Azure OpenAI for formatting
        prompt = f"""
        You are a nutritionist. I will provide you with the user context (age, gender, allergies, medical conditions, etc.) and a piece of text extracted from an image. Your job is to analyze the extracted text and provide a JSON response with the format below.

        ### **Instructions**

        - **There are 5 sections** in the response: userContext, productAnalysis, recommendations, ingredientList, allergicIngredients and summary.
        - **Based on the extracted text fill each section** with the relevant information.
        - **Fill out the additives carefully ** include any emsulsifiers, extracts, raising agent or any artificial flaours** in the ingredient list
        - **Extract the dietary preferences** from the user context and include them in the response.
        - **The format of nutritional breakdown is fixed only fill the value based on the extracted text** if not available then fill value as **null**.
        - Based on the ingredient list and the allergic items provided as input select the full ingredient name which are not suitable for the user. DO NOT COPY THE EXAMPLE LIST MAKE YOUR OWN.
        - Also provide the summary of the information in the summary section.
        
        ### **Input**:
        User Context:
        gender : {gender}
        age : {age}
        allergies : {allergic}
        diabetic : {diabetic}
        hypertension : {hypertension}
        cholesterol : {cholesterol}
        diet : {diet}


        Extracted Text:
        {extracted_text_str}

        ### **Expected Output**:
        {{
            "userContext": {{
                "dietaryPreferences": ["keto"],
                "allergies": ["onion", "apple", "grapes"],
                "medicalConditions": ["diabetic", "hypertension"]
            }},
            "productAnalysis": {{
            "suitability": "not suitable",
            "reasons": [
                "Artificial flavoring detected due to the presence of flavor enhancers (INS 627, INS 631).",
                "Contains acidity regulator (INS 270), which may affect individuals with sensitive digestion.",
                "High sodium content (161 mg per serving), which may not be ideal for individuals on a low-sodium diet.",
                "Processed carbohydrates present (18g per serving), making it less suitable for diabetics or keto diets.",
                "Contains added sugar (0.85g), though in small amounts.",
                "Milk solids detected—unsuitable for those with lactose intolerance."
            ],
            "observations": [
                {{
                "type": "additive",
                "message": "Artificial flavoring (INS 627, INS 631) detected.",
                "severity": "high"
                }},
                {{
                "type": "sodium",
                "message": "161mg per serving (7% daily value).",
                "severity": "medium"
                }},
                {{
                "type": "carbohydrates",
                "message": "18g per serving, which is high for a keto diet.",
                "severity": "high"
                }},
                {{
                "type": "sugar",
                "message": "Added sugar (0.85g) detected.",
                "severity": "medium"
                }}
            ]
            }},
            "servingSize": "30g",
            "nutritionalPerSize" : "100g"
            "nutritionalBreakdown":[
                {{
                    "label" : "carbohydrates",
                    "value" : "FILL YOUR VALUE HERE"
                }},
                {{
                    "label" : "dietary fiber",
                    "value" : "FILL YOUR VALUE HERE"
                }},
                {{
                    "label" : "total fat",
                    "value" : "FILL YOUR VALUE HERE"
                }},
                {{
                    "label" : "protein",
                    "value" : "FILL YOUR VALUE HERE"
                }},
                {{
                    "label" : "sodium",
                    "value" : "FILL YOUR VALUE HERE"
                }},
                {{
                    "label" : "calcium",
                    "value" : "FILL YOUR VALUE HERE"
                }},
                {{
                    "label" : "vitamin D",
                    "value" : "FILL YOUR VALUE HERE"
                }}
            ],
            "ingredientList": [
            "Corn (70%)",
            "Edible Vegetable Oil (Corn Oil)",
            "Corn Starch",
            "Iodized Salt",
            "Sugar",
            "Milk Solids (Skim Milk Powder, Whey Powder, Cheddar Cheese Powder (0.7%))",
            "Spices & Condiments (Oregano (0.3%), Parsley (0.1%), Black Pepper, Chilli, Turmeric)",
            "Onion Powder",
            "Acidity Regulator (INS 270)",
            "Anticaking Agent (INS 551)",
            "Flavour Enhancer (INS 627, INS 631)"
            ],
            "additivesSummary": [
            {{
                "name": "INS 270",
                "commonName": "Lactic Acid", 
                "purpose": "Acidity Regulator",
                "safety": "Generally Recognized as Safe"
            }},
            {{
                "name": "INS 551",
                "commonName": "Silicon Dioxide",
                "purpose": "Anti-caking Agent",
                "safety": "Safe"
            }},
            {{
                "name": "INS 627",
                "commonName": "Disodium Guanylate",
                "purpose": "Flavor Enhancer",
                "safety": "Moderate Risk (Not Recommended for Infants, Pregnant Women, or Gout Patients)"
            }},
            {{
                "name": "INS 631",
                "commonName": "Disodium Inosinate",
                "purpose": "Flavor Enhancer",
                "safety": "Moderate Risk (Not Recommended for Individuals with Kidney Issues)"
            }}
            ],
            "allergicIngredients": ["Corn", "Sugar"],
            "recommendations": {{
            "healthierAlternatives": [
                {{
                "type": "snack",
                "name": "Roasted Almonds",
                "suitability": ["keto", "diabetic"],
                "nutritionalBenefits": ["High in healthy fats", "No additives"]
                }},
                {{
                "type": "snack",
                "name": "Cheese Sticks",
                "suitability": ["keto", "diabetic"],
                "nutritionalBenefits": ["Good fat-to-protein ratio", "Low in carbohydrates"]
                }},
                {{
                "type": "snack",
                "name": "Unsweetened Yogurt with Chia Seeds",
                "suitability": ["diabetic", "low-sodium"],
                "nutritionalBenefits": ["Rich in probiotics", "Good source of protein"]
                }}
            ]
            }},
            "summary" : "provide the summary here"
        }}

        Return only valid JSON output with no explanations.
        """

        # Get response from Azure OpenAI
        response = azure_chat_openai([HumanMessage(content=prompt)])

        # Parse the response into JSON
        try:
            formatted_data = json.loads(response.content)
            if "nutritionalBreakdown" in formatted_data:
                formatted_data["nutritionalBreakdown"] = convert_to_grams(formatted_data["nutritionalBreakdown"], formatted_data["nutritionalPerSize"], formatted_data["servingSize"])

        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON response from OpenAI"}), 500
        # return jsonify({"formatted_data": json.loads(response.content)})
        return jsonify({"formatted_data": formatted_data})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # return jsonify({"formatted_data": "success"})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=True)
