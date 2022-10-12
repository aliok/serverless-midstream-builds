## Purpose:
Scripts in this repository help with creation of a Serverless midstream bundle that has all the images explicitly set
to use an image digest for being able to track what images are used.

## Prereqs:
- Python 3.6+
- Docker (podman not tested)


## Create and activatethe virtual environment:
```shell
python3 -m venv venv
source ./venv/bin/activate
pip install -r requirements.txt
```

When done:
```shell
deactivate
```

## Usage:
```shell
python3 main.py <branch> <target image name without tag>

#Example:
python3 main.py release-1.24 docker.io/aliok/serverless-operator-index
````

- Clone `release-1.24` branch of Serverless Operator repository into a temporary directory
- Collect all the Serverless images used in the CSV
- Pull the images and get their digests
- Replace the image tags with digests in the CSV
- Build a new index image (bundle image) with the modified CSV and the manifests
- Index image name with will be in this format:
  `<given target image name>:<branch>-<repository hash>-<yymmdd>-<hhMMSS>`
- For example: `docker.io/aliok/serverless-operator-index:release-1.24-0f3bffb5-20221012-142724`
- This index image then can be used in a catalogSource to install Serverless

## Troubleshooting
```shell
IMG="docker.io/aliok/serverless-operator-index:release-1.24-0f3bffb5-20221012-152236"

# CHECK IMAGE CONTENT
docker rm tmp_$$
rm -rf /tmp/manifests
docker create --name tmp_$$ ${IMG} /bin/sh
docker cp tmp_$$:/manifests /tmp/manifests
docker rm tmp_$$
open /tmp/manifests

# CHECK IMAGE LABELS AND METADATA
docker image inspect ${IMG}
```
