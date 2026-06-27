from flask import Flask, jsonify, request
from dotenv import load_dotenv
import uuid
from utils.azure_blob_utils import ComputerVisionProcessor
from azure.storage.blob import ContainerClient, ContentSettings
from utils.azure_openai_utils import FlashCardGenerator
from utils.file_utils import file_mimetype_allowed, find_content_type
import os
import codecs
import time
from pymongo import MongoClient, ReturnDocument
from datetime import datetime
from bson import ObjectId
import concurrent.futures
from flask_cors import CORS
from supermemo2 import SMTwo, year_mon_day

load_dotenv()

connection_string =  os.environ['STORAGE_ENDPOINT']

key = os.environ['VISION_KEY']
endpoint = os.environ['VISION_ENDPOINT']

gpt_key = os.environ['AZURE_OPENAI_KEY']
gpt_endpoint = os.environ['AZURE_OPENAI_ENDPOINT']
gpt_deployment_name = os.environ['AZURE_OPENAI_DEPLOYMENT_NAME']

container = ContainerClient.from_connection_string(conn_str=connection_string, container_name='imgdata')
gptClient = FlashCardGenerator(gpt_key, gpt_endpoint, gpt_deployment_name)

app = Flask(__name__)

client = MongoClient("mongodb://localhost:27017")
db = client.users
collection = db.users

CORS(app)

@app.route('/testupload', methods=['POST'])
def test_upload():
    files = request.files.getlist('files')

    time.sleep(5)
    print(files)
    return jsonify({"message" : "received files"})

@app.route('/')
def home_route():
    response = collection.find({}, {"last_updated" : 1, "title" : 1, "next_review" : 1})

    documents = []
    for document in response:
        document['_id'] = str(document['_id'])

        today_date = datetime.now().date()
        next_review = datetime.strptime(document.get('next_review', ''), "%d %b %Y").date()

        print(today_date, next_review)

        document["isDue"] = today_date >= next_review 

        documents.append(document)

    return jsonify({'message': documents})

@app.route('/uploads', methods=['POST'])
def upload_route():
    # collection.delete_many({})

    title = request.form.get('title')
    image_files = request.files.getlist('files')
    visionClient = ComputerVisionProcessor(key, endpoint)
    file_urls = []

    try:
        for image in image_files:
            if not file_mimetype_allowed(image):
                continue

            content_type = find_content_type(image)
            content_settings = ContentSettings(content_type)

            filename = str(uuid.uuid4()) + image.filename
            blob = container.upload_blob(name=filename, data=image, content_settings=content_settings)
            file_urls.append(blob.url)

        if len(file_urls) == 0:
            return jsonify({'message': 'failure', 'error' : True}), 400
        
        # sending the image files to the Azure Vision API

        lines = []
        for url in file_urls:
            visionClient.read_file_remote(url, lines)

        # writing the OCR results to the file

        with codecs.open('output.txt', 'w', encoding='utf-8', errors='ignore') as f:
            f.writelines(lines)

        # reading the OCR results from the file

        content = ''
        with codecs.open('output.txt', 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # Submit tasks to the threads pool
            flashcards_future = executor.submit(gptClient.generate_flashcards)
            summary_future = executor.submit(gptClient.generate_summary)

            # Wait for both tasks to complete
            flashcards_result = flashcards_future.result()
            summary_result = summary_future.result()

        responsemcqs = gptClient.generate_mcq()
        mcqs = []
        for mcq in responsemcqs:
            id = str(uuid.uuid4())
            mcq['id'] = id
            mcq['answer'] = int(mcq['answer'])
            mcqs.append(mcq)

        print(mcqs)

        dt = datetime.now().strftime("%Y-%m-%d")
        review = SMTwo.first_review(5, dt)
        review_details = {
            "easiness" : float(review.easiness),
            "interval" : int(review.interval),
            "repetitions" : int(review.repetitions),
        }

        if title == '' :
            title = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sample_data = {
            'title' : title,
            'image_urls': file_urls,
            'summary': summary_result,
            'content' : content,
            'flashcards': flashcards_result,
            'timestamp': datetime.now(),
            'review_details' : review_details,
            'last_updated': datetime.now().strftime("%d %b %Y"),
            'next_review' : review.review_date.strftime("%d %b %Y"),
            'mcqs' : mcqs
        }

        collection.insert_one(sample_data)

        print(sample_data)

        return jsonify({'message': 'success', 'error' : False})

    except Exception as e:
        print(e)
        return jsonify({'message': 'failure', 'error' : True}), 500


@app.route('/uploads/<string:id>', methods=['GET'])
def get_document_id(id):
    object_id = ObjectId(id)

    response = collection.find_one_and_update(
        {"_id" : object_id}, 
        {"$set" : {"last_updated" : datetime.now().strftime("%d %b %Y")}},
        return_document=ReturnDocument.AFTER
    )

    response["_id"] = str(response["_id"])

    return jsonify({"answer": response})

@app.route('/uploads/<string:id>/review', methods=['GET'])
def get_review(id):
    rate = request.args.get('rate')

    print(id)

    object_id = ObjectId(id)

    response = collection.find_one({"_id" : object_id})
    review = response.get('review_details', None)

    easiness = review.get('easiness', 0)
    interval = review.get('interval', 0)
    repetitions = review.get('repetitions', 0)

    sm2 = SMTwo(easiness, interval, repetitions).review(int(rate), datetime.now().strftime("%Y-%m-%d"), year_mon_day)
    next_review = sm2.review_date.strftime("%d %b %Y")
    print(next_review)

    updated_review = {
        "easiness" : float(sm2.easiness),
        "interval" : int(sm2.interval),
        "repetitions" : int(sm2.repetitions),
    }

    answer = collection.find_one_and_update(
        {"_id" : object_id}, 
        {"$set" : {"review_details" : updated_review, "next_review" : next_review}},
        return_document=ReturnDocument.AFTER
    )

    answer["_id"] = str(answer["_id"])

    return jsonify({"answer": answer, "error" : []})


@app.route('/uploads/<string:id>/chats/initialize', methods=['POST'])
def get_chat_initalized(id):
    object_id = ObjectId(id)

    response = collection.find_one({"_id" : object_id})
    response["_id"] = str(response["_id"])

    with open('output.txt', 'w', encoding='utf-8') as f:
        f.write(response['content'])

    gptClient.generate_vector_db()

    return jsonify({"answer": True, "error" : []})

@app.route('/uploads/chats', methods=['GET'])
def get_chat():
    query = request.args.get('query')

    response = gptClient.questions_and_answers(query)

    return response

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=True)




# {
#   "_id": {
#     "$oid": "64d7b8500d9d4df439d6649e"
#   },
#   "title": "new",
#   "image_urls": [
#     "https://mlsademo.blob.core.windows.net/imgdata/c3d760ab-18d0-4df8-a0b3-57e74b58aaa4WhatsApp%20Image%202023-08-02%20at%2022.01.472.jpg",
#     "https://mlsademo.blob.core.windows.net/imgdata/c7914390-44fb-400d-92f5-2ce0148b34b6WhatsApp%20Image%202023-08-02%20at%2022.01.47.jpg"
#   ],
#   "summary": "The article highlights the importance of soft skills in finance, citing the contrasting stories of a janitor who became a millionaire through investing and a Harvard-educated executive who went bankrupt. The author argues that finance is often taught as a math-based field, but soft skills are crucial in the industry. The article questions whether trial and error has taught us to become better with our personal finances.",
#   "content": "INTRODUCTION\n\nIn his will the former janitor left $2 million to his stepkids and\n\nmore than $6 million to his local hospital and library.\n\nThose who knew Read were baffled. Where did he get all that\n\nmoney?\n\nIt turned out there was no secret. There was no lottery win and\n\nno inheritance. Read saved what little he could and invested it\n\nin blue chip stocks. Then he waited, for decades on end, as tiny\n\nsavings compounded into more than $8 million.\n\nThat's it. From janitor to philanthropist.\n\nA few months before Ronald Read died, another man named\n\nRichard was in the news.\n\nRichard Fuscone was everything Ronald Read was not. A\n\nHarvard-educated Merrill Lynch executive with an MBA,\n\nFuscone had such a successful career in finance that he retired\n\nin his 40s to become a philanthropist. Former Merrill CEO\n\nDavid Komansky praised Fuscone's \"business savvy, leadership\n\nskills, sound judgment and personal integrity.\" Crain's business\n\nmagazine once included him in a \"40 under 40\" list of successful\n\nbusinesspeople.2\n\nBut then-like the gold-coin-skipping tech executive-\n\neverything fell apart.\n\nIn the mid-200os Fuscone borrowed heavily to expand an\n\n18,000-square foot home in Greenwich, Connecticut that had II\n\nbathrooms, two elevators, two pools, seven garages, and cost more\n\nthan $90,000 a month to maintain.\n\nThen the 2008 financial crisis hit.\n\nThe crisis hurt virtually everyone's finances. It apparently\n\nturned Fuscone's into dust. High debt and illiquid assets left\n\nhim bankrupt. \"I currently have no income,\" he allegedly told a\n\nbankruptcy judge in 2008.\n\nFirst his Palm Beach house was foreclosed.\n\nIn 2014 it was the Greenwich mansion's turn.\n\nFive months before Ronald Read left his fortune to charity,\n\n3\n\n\nINTRODUCTION\n\nThese soft skills are, I've come to realize, greatly underappreciated.\n\nFinance is overwhelmingly taught as a math-based field, where\n\nyou put data into a formula and the formula tells you what to do,\n\nand it's assumed that you'll just go do it.\n\nThis is true in personal finance, where you're told to have a six-\n\nmonth emergency fund and save 10% of your salary.\n\nIt's true in investing, where we know the exact historical\n\ncorrelations between interest rates and valuations.\n\nAnd it's true in corporate finance, where CFOs can measure\n\nthe precise cost of capital.\n\nIt's not that any of these things are bad or wrong. It's that\n\nknowing what to do tells you nothing about what happens in\n\nyour head when you try to do it.\n\nTwo topics impact everyone, whether you are interested in them\n\nor not: health and money.\n\nThe health care industry is a triumph of modern science, with\n\nrising life expectancy across the world. Scientific discoveries have\n\nreplaced doctors' old ideas about how the human body works, and\n\nvirtually everyone is healthier because of it.\n\nThe money industry-investing, personal finance, business\n\nplanning-is another story.\n\nFinance has scooped up the smartest minds coming from top\n\nuniversities over the last two decades. Financial Engineering was\n\nthe most popular major in Princeton's School of Engineering a\n\ndecade ago. Is there any evidence it has made us better investors?\n\nI have seen none.\n\nThrough collective trial and error over the years we learned\n\nhow to become better farmers, skilled plumbers, and advanced\n\nchemists. But has trial and error taught us to become better with\n\nour personal finances? Are we less likely to bury ourselves in\n\ndebt? More likely to save for a rainy day? Prepare for retirement?\n\n\n",
#   "flashcards": [
#     {
#       "question": "Where did the former janitor leave $2 million in his will?",
#       "answer": "to his stepkids"
#     },
#     {
#       "question": "Where did the former janitor leave more than $6 million in his will?",
#       "answer": "to his local hospital and library"
#     },
#     {
#       "question": "How did the former janitor accumulate his wealth?",
#       "answer": "by saving what little he could and investing in blue chip stocks"
#     },
#     {
#       "question": "Who is Richard Fuscone?",
#       "answer": "a Harvard-educated Merrill Lynch executive"
#     },
#     {
#       "question": "What did Richard Fuscone borrow heavily for?",
#       "answer": "to expand his home in Greenwich, Connecticut"
#     },
#     {
#       "question": "What happened to Richard Fuscone's finances after the 2008 financial crisis?",
#       "answer": "they were hurt and he became bankrupt"
#     },
#     {
#       "question": "What is Finance overwhelmingly taught as?",
#       "answer": "a math-based field"
#     },
#     {
#       "question": "What are two topics that impact everyone?",
#       "answer": "health and money"
#     },
#     {
#       "question": "What is Financial Engineering?",
#       "answer": "a popular major in Princeton's School of Engineering a decade ago"
#     },
#     {
#       "question": "Has Financial Engineering made us better investors?",
#       "answer": "no evidence has been seen so far"
#     },
#     {
#       "question": "Have we learned to become better with our personal finances through trial and error?",
#       "answer": "unclear and not mentioned"
#     }
#   ],
#   "timestamp": {
#     "$date": "2023-08-12T22:20:24.052Z"
#   },
#   "review_details": {
#     "easiness": 2.6,
#     "interval": 1,
#     "repetitions": 1
#   },
#   "last_updated": "12 Aug 2023",
#   "next_review": "13 Aug 2023"
# }

