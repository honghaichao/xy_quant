from utils.feishu_image import FeishuImageClient, FeishuImageError


def test_upload_image_builds_message(monkeypatch, tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"fakepng")

    class Resp:
        status_code = 200
        text = "ok"
        def json(self):
            return {"code": 0, "data": {"image_key": "img_key_123"}}

    def fake_post(url, headers=None, data=None, files=None, timeout=None, json=None):
        assert url.endswith("/open-apis/im/v1/images")
        assert data["image_type"] == "message"
        assert "Authorization" in headers
        return Resp()

    monkeypatch.setattr("requests.post", fake_post)
    client = FeishuImageClient("token")
    key = client.upload_image(img)
    assert key == "img_key_123"
    assert client.build_image_message(key) == {"msg_type": "image", "content": {"image_key": "img_key_123"}}


def test_upload_image_missing_file():
    client = FeishuImageClient("token")
    try:
        client.upload_image("/no/such/file.png")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
