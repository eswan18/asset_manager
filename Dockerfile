FROM public.ecr.aws/lambda/python:3.8

WORKDIR /var/task

ADD . /var/task/

RUN pwd && ls .

RUN pip install -e .

CMD ["lambda_entrypoint.lambda_handler"]
