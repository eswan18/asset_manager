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
]

typecheck_requires = requires + [
    'mypy',
    'boto3-stubs[essential]',
    'pandas-stubs',
    'google-api-python-client-stubs'
]

lint_requires = requires + [
    'flake8'
]

setup(
    name='asset_manager',
    version='0.0.9',
    packages=['asset_manager'],
    python_requires='>=3.8',
    install_requires=requires,
    extras_require={
        'tests': tests_require,
        'typecheck': typecheck_requires,
        'lint': lint_requires
    },
    license='MIT',
    long_description=open('README.md').read(),
)
