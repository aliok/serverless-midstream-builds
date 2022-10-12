import datetime
import json
import os.path
import shutil
import sys
import tempfile

import docker
import git

REPOSITORY = "https://github.com/openshift-knative/serverless-operator.git"
CSV_FILE_NAME = "olm-catalog/serverless-operator/manifests/serverless-operator.clusterserviceversion.yaml"
# prefixes for images that we add the sha256 digest to
IMAGE_PREFIXES = [
    "registry.ci.openshift.org/openshift/knative-",
    "registry.ci.openshift.org/knative/openshift-serverless-",
    "registry.ci.openshift.org/knative/release-"
]


def collect_images(repo_root, image_prefix):
    csv_file = os.path.join(repo_root, CSV_FILE_NAME)
    print(f"Collecting images from the CSV file: {csv_file} with prefix {image_prefix}")
    with open(csv_file, "r") as f:
        lines = f.readlines()

    # first collect the images to pull
    images = []
    for line in lines:
        line = line.strip()
        if image_prefix in line:
            # extract image from line in one of these formats:
            # value: "registry.ci.openshift.org/openshift/knative-v1.5.0:knative-serving-autoscaler-hpa"
            # image: registry.ci.openshift.org/openshift/knative-v1.4.1:kn-cli-artifacts
            # image: "registry.ci.openshift.org/openshift/knative-v1.5.0:knative-serving-queue"
            # image: registry.ci.openshift.org/knative/openshift-serverless-v1.24.0:knative-operator
            start_of_prefix = line.find(image_prefix)
            img = line[start_of_prefix:]
            # remove the trailing quote
            if img.endswith('"'):
                img = img[:-1]
            images.append(img)

    # deduplicate images
    images = sorted(list(set(images)))
    return images


def pull_images(images, docker_client):
    print(f"Going to pull {len(images)} images.")
    for i, img in enumerate(images):
        print(f"Pulling {img}: {i + 1}/{len(images)}")
        for _ in docker_client.api.pull(img, stream=True, decode=True):
            # do not actually write the Docker output but have some kind of indicator
            # print(json.dumps(line, indent=4))
            print(".", end="", flush=True)
        print("done", flush=True)


def create_image_map(images, docker_client):
    img_map = {}
    print(f"Creating image map...")
    for i, img_name in enumerate(images):
        img = docker_client.images.get(img_name)
        all_digests = img.attrs["RepoDigests"]
        latest_digest = all_digests[0]
        digest_without_image_name = latest_digest.split("@")[1]
        img_map[img_name] = digest_without_image_name
    return img_map


def replace_images(repo_root, img_map):
    csv_file = os.path.join(repo_root, CSV_FILE_NAME)
    print(f"Replacing images in the CSV file: {csv_file}")
    with open(csv_file, 'r') as file:
        csv_content = file.read()

    for img_name, img_digest in img_map.items():
        # there are some image names that include others, so, we cannot do a blind replace
        # for example "registry.ci.openshift.org/openshift/knative-v1.3.0:knative-serving-domain-mapping-webhook"
        # contains the name "registry.ci.openshift.org/openshift/knative-v1.3.0:knative-serving-domain-mapping"

        # replace image within quotes:
        # value: "registry.ci.openshift.org/openshift/knative-v1.5.0:knative-serving-autoscaler-hpa"
        # new  : "registry.ci.openshift.org/openshift/knative-v1.5.0:knative-serving-autoscaler-hpa@sha256:..."
        csv_content = csv_content.replace(f'"{img_name}"', f'"{img_name}@{img_digest}"')

        # replace no quote but line ending with image name:
        # OLD:
        # image: registry.ci.openshift.org/knative/openshift-serverless-v1.24.0:openshift-knative-operator\n
        # NEW:
        # image: registry.ci.openshift.org/knative/openshift-serverless-v1.24.0:openshift-knative-operator@sha256:...\n
        csv_content = csv_content.replace(f'{img_name}\n', f'{img_name}@{img_digest}\n')

    with open(csv_file, 'w') as file:
        file.write(csv_content)


def build_index_image(repo_root, docker_client, target_img_name):
    print(f"Building index image {target_img_name}...")
    image_root_dir = os.path.join(repo_root, "olm-catalog", "serverless-operator")
    for line in docker_client.api.build(path=image_root_dir, tag=target_img_name, decode=True):
        if "stream" in line:
            print(line["stream"], end="")
        else:
            print(line)


def execute(repo_root, target_img_name):
    print("Creating Docker client...")
    docker_client = docker.from_env()

    print("Executing...")

    images = []
    for prefix in IMAGE_PREFIXES:
        images.extend(collect_images(repo_root, prefix))
    print(f"Collected {len(images)} images:")
    for img in images:
        print(f"  {img}")

    pull_images(images, docker_client)

    img_map = create_image_map(images, docker_client)
    print("Image map:")
    print(json.dumps(img_map, indent=4))

    replace_images(repo_root, img_map)

    build_index_image(repo_root, docker_client, target_img_name)

class ProgressPrinter(git.RemoteProgress):
    def update(self, op_code, cur_count, max_count=None, message=''):
        if message:
            print(".", end="", flush=True)


def clone(branch, temp_dir):
    print(f"Cloning {REPOSITORY} and branch {branch} to {temp_dir}")
    repo = git.Repo.clone_from(REPOSITORY, os.path.join(temp_dir), branch=branch, progress=ProgressPrinter())
    print("done", flush=True)
    print(f"Cloned {REPOSITORY} to {temp_dir}")
    print(f"Current commit: {repo.head.commit}")
    return repo


def print_help():
    print(f"Usage: python3 {sys.argv[0]} <branch> <target image name without tag>")
    print(
        f"Example: python3 {sys.argv[0]} release-1.24 quay.io/aliok/serverless-operator-index")


def main():
    if len(sys.argv) != 3:
        print_help()
        sys.exit(1)
    branch = sys.argv[1]
    target_img_name_base = sys.argv[2]

    if ":" in target_img_name_base:
        print("Target image name should not have a tag.")
        print_help()
        sys.exit(1)

    temp_dir = tempfile.mkdtemp(prefix="serverless-operator-")

    try:
        repo = clone(branch, temp_dir)
        tag = f'{branch}-{repo.git.rev_parse(repo.head, short=True)}-{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}'
        target_img_name = f"{target_img_name_base}:{tag}"
        print(f"Target image name: {target_img_name}")
        execute(temp_dir, target_img_name)

        print(f"Now push {target_img_name} manually using the following command:")
        print(f"docker push {target_img_name}")
    finally:
        if 1 == 0:
            print(f"Removing {temp_dir}")
            shutil.rmtree(temp_dir)


if __name__ == '__main__':
    main()
