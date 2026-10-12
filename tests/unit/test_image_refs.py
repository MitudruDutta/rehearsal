"""Image references can never become docker options, and built image tags never collide across workspaces."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rehearsal.api.app import ApplicationIn
from rehearsal.compiler.pipeline import AppInput, Compiler
from rehearsal.core.contracts import ServiceSpec, WorldManifest
from rehearsal.runner import runtime

OPTIONS = ["--privileged", "-v/:/host", "--volume=/:/host", "-", "img --privileged", "img\n--privileged"]


def catalog_images() -> list[str]:
    data = yaml.safe_load(Path("rehearsal/assets/catalog.yaml").read_text())
    return [ref for app in data["applications"] for ref in app.get("images", {}).values()]


def test_every_catalog_image_is_accepted():
    for ref in catalog_images():
        assert ServiceSpec(name="app", image=ref).image == ref


@pytest.mark.parametrize("ref", OPTIONS)
def test_option_like_images_are_refused(ref):
    with pytest.raises(ValidationError):
        ServiceSpec(name="app", image=ref)
    with pytest.raises(ValidationError):
        ApplicationIn(name="a", source={"kind": "upload"}, images={"app": ref})


def test_owner_cannot_name_a_server_built_image():
    with pytest.raises(ValidationError):
        ApplicationIn(name="a", source={"kind": "upload"}, images={"app": "rh-img-0123456789-web"})


@pytest.mark.parametrize("user", ["--privileged", "-0", "root --privileged"])
def test_option_like_users_are_refused(user):
    with pytest.raises(ValidationError):
        ServiceSpec(name="app", image="redis:7", user=user)


def test_docker_run_ends_options_before_the_image():
    manifest = WorldManifest(name="t", services=[ServiceSpec(name="app", image="redis:7", port=6379, user="999:999", entrypoint=["redis-server", "--save", ""])])
    inst = runtime.WorldInstance(runtime.InstanceRecord(
        "test", manifest.model_dump(mode="json", by_alias=True), {}, "token",
        images={"app": "redis:7"}, volumes={"app": [], "providers": []},
    ))
    args = inst._service_args(inst.manifest.services[0])
    i = args.index("--")
    assert args[i + 1] == "redis:7" and args[i + 2:] == ["--save", ""]
    assert "--user=999:999" in args and "--entrypoint=redis-server" in args


def test_built_image_tags_differ_per_application(tmp_path):
    keys = {Compiler.world_key(NSCompiler(app_id)) for app_id in ("app_1", "app_2")}
    assert len(keys) == 2


class NSCompiler:
    def __init__(self, app_id: str):
        self.app = AppInput("gitea", Path("."), provenance={"application_id": app_id})
