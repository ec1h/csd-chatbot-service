# Use AWS Lambda Python base image (Python 3.11 – change if you use 3.10)
FROM public.ecr.aws/lambda/python:3.11

# Optional: set working dir (Lambda uses /var/task by default)
WORKDIR /var/task

# Copy dependency file and install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app code
COPY . .

# (Optional) default environment values – real ones should be set in Lambda config
# ENV ENV=qa
# ENV LOG_LEVEL=info

# Tell Lambda which handler to invoke: module.function
# Here: lambda_app.py -> handler variable
CMD ["lambda_app.handler"]
