from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import pytesseract
from PIL import Image
import os
import fitz
from .models import fileData
import boto3
from django.conf import settings
import openai
from openai import OpenAI

openai.api_key = settings.OPENAI_KEY


def s3_upload(file):
    # The below function is to upload a file to S3 and return the link to access the file
    if file:
        try:
            file_path = os.path.join(settings.MEDIA_ROOT, file.name)
            with open(file_path, "wb") as f:
                for chunk in file.chunks():
                    f.write(chunk)

            aws_access_key_id = settings.AWS_ACCESS_KEY_ID
            aws_secret_access_key = settings.AWS_SECRET_ACCESS_KEY
            aws_region = settings.AWS_S3_REGION_NAME
            s3 = boto3.resource(
                "s3",
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=aws_region,
            )
            bucket_name = settings.AWS_STORAGE_BUCKET_NAME

            s3.Bucket(bucket_name).upload_file(
                file_path,
                "infer-soft/" + file.name,
            )
            
            file_url = f"https://{bucket_name}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/infer-soft/{file.name}"
            os.remove(file_path)

            return file_url
        except Exception:
            return ""



@csrf_exempt
def fileUpload(request):
    # The below function is to process all the files that are uploaded by the user
    # Steps: 
    #   Reads the files
    #   Using the fitz module, reads the file content    
    #   Stores the file in S3 to avoid storing files in the database
    #   Saves the S3 link, content of the file and name of the file in the database

    if request.method == 'POST':
        files = request.FILES.getlist('files')

        if not files:
            return JsonResponse({'error': 'No files uploaded'}, status=400)

        ocr_results = []

        for file in files:
            try:
                path = default_storage.save(file.name, ContentFile(file.read()))
                temp_file_path = default_storage.path(path)
                
                if file.name.lower().endswith('.pdf'):
                    pdf_document = fitz.open(temp_file_path)
                    text = ""
                    for page_num in range(len(pdf_document)):
                        page = pdf_document.load_page(page_num)
                        pix = page.get_pixmap()
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        text += pytesseract.image_to_string(img)
                    pdf_document.close()
                else:
                    with open(temp_file_path, 'rb') as f:
                        image = Image.open(f)
                        text = pytesseract.image_to_string(image)

                ocr_results.append({'file_name': file.name, 'text': text})

                fileLink = s3_upload(file)
                default_storage.delete(temp_file_path)

                 # Create a new User object and save it to the database
                data = fileData.objects.create(fileName=file.name, data=text, fileLink=fileLink)
                data.save()

            except Exception as e:
                ocr_results.append({'file_name': file.name, 'error': str(e)})

        return JsonResponse({'ocr_results': ocr_results})

    return JsonResponse({'error': 'Method not allowed'}, status=405)


def get_snippet_from_gpt(text, prompt):
    # The below function is to perform the search operation on the data from the pdf files using GPT 4 Turbo model
    try:
        client = OpenAI(api_key=openai.api_key,)

        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system",
                    "content": prompt },
                {"role": "user", "content": text}
            ],
            model="gpt-3.5-turbo", 
        )

        val = chat_completion.choices[0].message.content
    except Exception as e:
        val = ""

    return val



def search(request):
    # The below function is to search for the a query that the User provides
    # Steps: 
    #   Retrieves all the contents of the all the files 
    #   Uses GPT 4 Turbo Model to evaluate the prompt based on the contents of the file  
    #   Returns the final result in the form of a string

    prompt = request.GET.get("search_query")

    data_list = fileData.objects.values_list('data', flat=True)
    total_text = ""
    for data in data_list:
        total_text += data


    # Use gpt to return the result based on the file's contents
    val = get_snippet_from_gpt(total_text, prompt)     
    return JsonResponse({'message': val}, status=200)


def getUploadedFiles(request):
    # The below function is to retrieve all the files which have already been uploaded
    # Steps: 
    #   Retrieves all the file names and the file links
    #   Returns this list to the frontend

    files = fileData.objects.values('fileName', 'fileLink')
    return JsonResponse({'files': list(files)})