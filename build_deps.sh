pip install . --target ./package
cd package
zip -r ../deployment-package.zip .
cd ..
zip -g deployment-package.zip lambda_entrypoint.py
