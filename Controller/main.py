from kubernetes import client, config, watch
from concurrent.futures import ThreadPoolExecutor

CONTROLLER_LABEL_PREFIX="AUT-CLOUD-"
CONFIGMAP_NAME = "controller-configmap"
RESOURCE_VERSION_KEY = "resource-version"

def create_deployment(application_name, image, tag, port, replicas, namespace):
    # Create a Deployment object
    deployment = client.V1Deployment()
    deployment.metadata = client.V1ObjectMeta(
        name=application_name,
        namespace=namespace,
        labels={f"{CONTROLLER_LABEL_PREFIX}{namespace}-{application_name}": "true"}  # Add controller label
    )

    # Check if the Deployment already exists
    existing_deployments = client.AppsV1Api().list_namespaced_deployment(namespace=namespace)
    for existing_deployment in existing_deployments.items:
        if f"{CONTROLLER_LABEL_PREFIX}{namespace}-{application_name}" in existing_deployment.metadata.labels:
            print(f"Deployment for {application_name} already exists. Skipping.")
            return

    # Set the image and port for the Deployment
    deployment.spec = client.V1DeploymentSpec(
        replicas=replicas,
        selector=client.V1LabelSelector(match_labels={"app": application_name}),
        template=client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": application_name}),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="application",
                        image="{}:{}".format(image, tag),
                        ports=[client.V1ContainerPort(container_port=port, protocol="TCP")]
                    )
                ]
            )
        )
    )

    # Create the Deployment
    try:
        client.AppsV1Api().create_namespaced_deployment(namespace=namespace, body=deployment)
        print("Deployment created successfully")
    except Exception as e:
        print("Failed to create deployment: ", e)

def create_service(application_name, port, namespace):
    # Create a Service object
    service = client.V1Service()
    service.metadata = client.V1ObjectMeta(
        name=application_name,
        namespace=namespace,
        labels={f"{CONTROLLER_LABEL_PREFIX}{namespace}-{application_name}": "true"}  # Add controller label
    )

    # Check if the Service already exists
    existing_services = client.CoreV1Api().list_namespaced_service(namespace=namespace)
    for existing_service in existing_services.items:
        if f"{CONTROLLER_LABEL_PREFIX}{namespace}-{application_name}" in existing_service.metadata.labels:
            print(f"Service for {application_name} already exists. Skipping.")
            return

    # Set the port for the Service
    service.spec = client.V1ServiceSpec(
        selector={"app": application_name},
        type="ClusterIP",
        ports=[client.V1ServicePort(
            protocol="TCP",
            port=port,
            target_port=port
        )]
    )

    # Create the Service
    try:
        client.CoreV1Api().create_namespaced_service(namespace=namespace, body=service)
        print("Service created successfully")
    except Exception as e:
        print("Failed to create service: ", e)

def delete_deployment(application_name, namespace):
    # Delete the Deployment
    try:
        client.AppsV1Api().delete_namespaced_deployment(name=application_name, namespace=namespace)
        print(f"Deployment {application_name} deleted successfully in namespace {namespace}")
    except Exception as e:
        print(f"Failed to delete deployment {application_name} in namespace {namespace}: {e}")

def delete_service(application_name, namespace):
    # Delete the Service
    try:
        client.CoreV1Api().delete_namespaced_service(name=application_name, namespace=namespace)
        print(f"Service {application_name} deleted successfully in namespace {namespace}")
    except Exception as e:
        print(f"Failed to delete service {application_name} in namespace {namespace}: {e}")

def update_deployment(application_name, image, tag, port, replicas, namespace):
    # Update the Deployment
    try:
        existing_deployment = client.AppsV1Api().read_namespaced_deployment(name=application_name, namespace=namespace)
        existing_deployment.spec.replicas = replicas
        existing_deployment.spec.template.spec.containers[0].image = f"{image}:{tag}"
        existing_deployment.spec.template.spec.containers[0].ports[0].container_port = port
        client.AppsV1Api().replace_namespaced_deployment(name=application_name, namespace=namespace, body=existing_deployment)
        print(f"Deployment {application_name} updated successfully in namespace {namespace}")
    except Exception as e:
        print(f"Failed to update deployment {application_name} in namespace {namespace}: {e}")

def update_service(application_name, port, namespace):
    # Update the Service
    try:
        existing_service = client.CoreV1Api().read_namespaced_service(name=application_name, namespace=namespace)
        existing_service.spec.ports[0].port = port
        existing_service.spec.ports[0].target_port = port
        client.CoreV1Api().replace_namespaced_service(name=application_name, namespace=namespace, body=existing_service)
        print(f"Service {application_name} updated successfully in namespace {namespace}")
    except Exception as e:
        print(f"Failed to update service {application_name} in namespace {namespace}: {e}")


def reconcile(application, type_of_event):
    # Extract application details
    application_name = application["metadata"]["name"]
    namespace = application["metadata"]["namespace"]  # Extract namespace
    image = application["spec"]["image"]
    tag = application["spec"]["tag"]
    port = application["spec"]["port"]
    replicas = application["spec"]["replicas"]

    if type_of_event == "ADDED":
        create_deployment(application_name, image, tag, port, replicas, namespace)
        create_service(application_name, port, namespace)
    elif type_of_event == "MODIFIED":
        existing_deployment = client.AppsV1Api().read_namespaced_deployment(name=application_name,
                                                                            namespace=namespace)
        if existing_deployment.metadata.labels.get(f"{CONTROLLER_LABEL_PREFIX}{namespace}-{application_name}") == "true":
            update_deployment(application_name, image, tag, port, replicas, namespace)
            update_service(application_name, port, namespace)
    elif type_of_event == "DELETED":
        delete_deployment(application_name, namespace)
        delete_service(application_name, namespace)

def read_resource_version():
    try:
        configmap = client.CoreV1Api().read_namespaced_config_map(name=CONFIGMAP_NAME, namespace="default")
        return configmap.data.get(RESOURCE_VERSION_KEY, "0")
    except client.rest.ApiException as e:
        if e.status == 404:
            return "0"
        else:
            print(f"Failed to read ConfigMap: {e}")
            return "0"

def write_resource_version(resource_version):
    try:
        configmap = client.CoreV1Api().read_namespaced_config_map(name=CONFIGMAP_NAME, namespace="default")
        if not configmap.data:
            configmap.data = {}
        configmap.data[RESOURCE_VERSION_KEY] = resource_version
        client.CoreV1Api().replace_namespaced_config_map(name=CONFIGMAP_NAME, namespace="default", body=configmap)
    except client.rest.ApiException as e:
        if e.status == 404:
            # ConfigMap does not exist, create a new one
            configmap = client.V1ConfigMap(
                api_version="v1",
                kind="ConfigMap",
                metadata=client.V1ObjectMeta(name=CONFIGMAP_NAME),
                data={RESOURCE_VERSION_KEY: resource_version}
            )
            client.CoreV1Api().create_namespaced_config_map(namespace="default", body=configmap)
        else:
            print(f"Failed to write ConfigMap: {e}")

def watch_namespace(namespace, resource_version):
    print("hello im here " , namespace)
    while True:
        stream = watch.Watch().stream(client.CustomObjectsApi().list_namespaced_custom_object,
                                      group="operators.pyhp2017.github.io",
                                      version="v1", plural="applications",
                                      namespace=namespace,
                                      resource_version=resource_version)
        for event in stream:
            resource = event["object"]
            type_of_event = event['type'] # ADDED - MODIFIED - DELETED
            resource_version = resource["metadata"]["resourceVersion"]
            write_resource_version(resource_version)
            reconcile(resource, type_of_event)

def watch_applications():
    resource_version = read_resource_version()
    namespaces = client.CoreV1Api().list_namespace().items

    with ThreadPoolExecutor(max_workers=len(namespaces)) as executor:
        for namespace in namespaces:
            executor.submit(watch_namespace, namespace.metadata.name, resource_version)

def main():
    # Set up the Kubernetes client
    config.load_kube_config()

    # Watch for changes in the "applications" CRD
    watch_applications()

if __name__ == "__main__":
    main()
