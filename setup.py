from distutils.core import setup

requires = [
    'altair',
    'pandas',
    'boto3',
    'google-api-python-client',
    'google-auth-httplib2',
    'google-auth-oauthlib'
]

tests_require = requires + [
    'hypothesis',
    'pytest',
    'pytest-cov',
    'mypy'
]

setup(
    name='asset_manager',
    version='0.0.9',
    packages=['asset_manager'],
    install_requires=requires,
    extras_require={'tests': tests_require},
    license='MIT',
    long_description=open('README.md').read(),
)
