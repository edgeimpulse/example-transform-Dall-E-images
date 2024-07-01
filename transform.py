import os, sys, shutil
import requests
import argparse
import json
from openai import OpenAI
from openai import AzureOpenAI
import time
import traceback

if not os.getenv('EI_PROJECT_API_KEY'):
    print('Missing EI_PROJECT_API_KEY')
    sys.exit(1)

API_KEY = os.environ.get("EI_PROJECT_API_KEY")
INGESTION_HOST = os.environ.get("EI_INGESTION_HOST", "edgeimpulse.com")

# these are the three arguments that we get in
parser = argparse.ArgumentParser(description='Use OpenAI Dall-E to generate an image dataset for classification from your prompt')
parser.add_argument('--service', type=str, required=False, help="Either \"openai\" or \"azure\"", default="openai")
parser.add_argument('--prompt', type=str, required=True, help="Prompt to give Dall-E to generate the images")
parser.add_argument('--label', type=str, required=True, help="Label for the images")
parser.add_argument('--images', type=int, required=True, help="Number of images to generate")
parser.add_argument('--upload-category', type=str, required=False, help="Which category to upload data to in Edge Impulse", default='split')
parser.add_argument('--synthetic-data-job-id', type=int, required=False, help="If specified, sets the synthetic_data_job_id metadata key")
parser.add_argument('--skip-upload', type=bool, required=False, help="Skip uploading to EI", default=False)
parser.add_argument('--out-directory', type=str, required=False, help="Directory to save images to", default="output")
parser.add_argument('--azure-endpoint', type=str, required=False, help="E.g. 'https://XXX.openai.azure.com/', required if service is \"azure\"")
parser.add_argument('--azure-deployment', type=str, required=False, help="Model deployment name from Azure OpenAI Studio, required if service is \"azure\"")
args, unknown = parser.parse_known_args()
if not os.path.exists(args.out_directory):
    os.makedirs(args.out_directory)
output_folder = args.out_directory

INGESTION_URL = "https://ingestion." + INGESTION_HOST
if (INGESTION_HOST.endswith('.test.edgeimpulse.com')):
    INGESTION_URL = "http://ingestion." + INGESTION_HOST
if (INGESTION_HOST == 'host.docker.internal'):
    INGESTION_URL = "http://" + INGESTION_HOST + ":4810"

# the replacement looks weird; but if calling this from CLI like "--prompt 'test\nanother line'" we'll get this still escaped
# (you could use $'test\nanotherline' but we won't do that in the Edge Impulse backend)
prompt = args.prompt.replace('\\n', '\n')
label = args.label
base_images_number = args.images
upload_category = args.upload_category
service = args.service

if (service == 'openai'):
    if not os.getenv('OPENAI_API_KEY'):
        print('Missing OPENAI_API_KEY')
        sys.exit(1)

    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
elif (service == 'azure'):
    if not os.getenv('AZURE_OPENAI_API_KEY'):
        print('Missing AZURE_OPENAI_API_KEY')
        sys.exit(1)
    if not args.azure_endpoint:
        print('Missing --azure-endpoint')
        sys.exit(1)
    if not args.azure_deployment:
        print('Missing --azure-deployment')
        sys.exit(1)

    client = AzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version='2024-02-01',
        azure_endpoint=args.azure_endpoint,
        azure_deployment=args.azure_deployment,
    )
else:
    print('--service is invalid, should be "azure" or "openai" - but was "' + service + '"')
    sys.exit(1)

if (upload_category != 'split' and upload_category != 'training' and upload_category != 'testing'):
    print('Invalid value for "--upload-category", should be "split", "training" or "testing" (was: "' + upload_category + '")')
    exit(1)

output_folder = 'output/'
# Check if output directory exists and create it if it doesn't
if not os.path.exists(output_folder):
    os.makedirs(output_folder)
else:
    shutil.rmtree(output_folder)
    os.makedirs(output_folder)

epoch = int(time.time())

print('Prompt:', prompt)
print('Number of images:', base_images_number)
print('')

for i in range(base_images_number):
    print(f'Creating image {i+1} of {base_images_number} for {label}...', end='', flush=True)
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )

        image_url = response.data[0].url

        fullpath = os.path.join(args.out_directory,f'{label}.{epoch}.{i}.png')
        with open(fullpath, 'wb+') as f:
            png = requests.get(image_url).content
            f.write(png)

        if not args.skip_upload:
            res = requests.post(url=INGESTION_URL + '/api/' + upload_category + '/files',
                headers={
                    'x-label': label,
                    'x-api-key': API_KEY,
                    'x-metadata': json.dumps({
                        'generated_by': 'dall-e-3',
                        'prompt': prompt,
                    }),
                    'x-synthetic-data-job-id': str(args.synthetic_data_job_id) if args.synthetic_data_job_id is not None else None,
                },
                files = { 'data': (os.path.basename(fullpath), png, 'image/png') }
            )
            if (res.status_code != 200):
                raise Exception('Failed to upload file to Edge Impulse (status_code=' + str(res.status_code) + '): ' + res.content.decode("utf-8"))
            else:
                body = json.loads(res.content.decode("utf-8"))
                if (body['success'] != True):
                    raise Exception('Failed to upload file to Edge Impulse: ' + body['error'])
                if (body['files'][0]['success'] != True):
                    raise Exception('Failed to upload file to Edge Impulse: ' + body['files'][0]['error'])

        print(' OK')

    except Exception as e:
        print('')
        print('Failed to complete DALL-E generation:', e)
        print(traceback.format_exc())
        exit(1)
