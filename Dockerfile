FROM amazonlinux:2023

ENV PYTHONUNBUFFERED=1

RUN yum update -y && \
    yum install -y python3.11 python3.11-pip gcc gcc-c++ make && \
    yum clean all && rm -rf /var/cache/yum

WORKDIR /app

COPY requirements.txt constraints.txt ./

RUN pip3.11 install --no-cache-dir --upgrade pip && \
    pip3.11 install --no-cache-dir -r requirements.txt -c constraints.txt

COPY . .

EXPOSE 8001

CMD ["python3.11", "app.py"]
