import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="nonebot-plugin-distributed-blacklist",
    version="1.0.1",
    author="Tosd0",
    author_email="tntobsidian@126.com",
    description="基于PostgreSQL的分布式黑名单系统",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-repo/nonebot-plugin-distributed-blacklist",
    packages=setuptools.find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.9",
    install_requires=[
        "nonebot2>=2.3.0,<3.0.0",
        "nonebot-adapter-onebot>=2.3.0",
        "nonebot-plugin-apscheduler>=0.5.0",
        "asyncpg>=0.28.0",
        "pydantic>=1.10.0",
    ],
    extras_require={
        "dev": [
            "pytest",
            "pytest-asyncio",
            "black",
            "isort",
            "flake8",
        ]
    },
    package_data={
        "nonebot_plugin_distributed_blacklist": ["*.py"],
    },
)