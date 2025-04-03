import setuptools

# read the contents of your README file
from pathlib import Path
long_description = (Path(__file__).parent/"README.md").read_text()


setuptools.setup(
    name="hololinked",
    version="0.2.10",
    author="Vignesh Vaidyanathan",
    author_email="vignesh.vaidyanathan@hololinked.dev",
    description="A ZMQ-based Object Oriented RPC tool-kit for instrument control/data acquisition or controlling generic python objects.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://hololinked.readthedocs.io/en/latest/index.html",
    packages=[
        'hololinked',
        'hololinked.server',
        'hololinked.rpc',
        'hololinked.client',
        'hololinked.param'    
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Intended Audience :: Information Technology",
        "Intended Audience :: Science/Research",
        "Intended Audience :: Healthcare Industry",
        "Intended Audience :: Manufacturing", 
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Education",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: Browsers",
        "Topic :: Scientific/Engineering :: Human Machine Interfaces",
        "Topic :: System :: Hardware",
        "Development Status :: 4 - Beta"
    ],    
    python_requires='>=3.11',
    install_requires=[
        "argon2-cffi>=23.0.0",
        "ifaddr>=0.2.0",
        "msgspec>=0.18.6",
        "pyzmq>=25.1.0",
        "SQLAlchemy>=2.0.21",
        "SQLAlchemy_Utils>=0.41.1",
        "tornado>=6.3.3",
        "jsonschema>=4.22.0"
    ],
    license="BSD-3-Clause",
    license_files=('license.txt', 'licenses/param-LICENSE.txt', 'licenses/pyro-LICENSE.txt'),
    keywords=["data-acquisition", "zmq-rpc", "SCADA/IoT", "Web of Things"]
)
 