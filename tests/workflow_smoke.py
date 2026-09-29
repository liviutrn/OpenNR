"""Run a small CPU train/resume/evaluate/export regression with synthetic inputs."""
from pathlib import Path
import json
import sys

import onnx
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from opennr_paths import external_path
from opennr_student import OpenNRStudent, StudentConfig


def main():
    destination = external_path('output') / 'validation' / 'workflow-smoke-2.15.0'
    destination.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    torch.manual_seed(2150)
    config = StudentConfig(width=8, blocks=1, guided=True)
    model = OpenNRStudent(config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    rgb = torch.rand(1, 3, 64, 64)
    guides = torch.rand(1, 5, 16, 16)
    context = torch.rand(1, 8, 24, 24)
    target = rgb * .9

    def update(network, state):
        state.zero_grad()
        loss = (network(rgb, guides, context) - target).abs().mean()
        assert torch.isfinite(loss)
        loss.backward()
        state.step()

    for _ in range(2):
        update(model, optimizer)
    checkpoint = destination / 'smoke.pt'
    torch.save({'model': model.state_dict(), 'optimizer': optimizer.state_dict()}, checkpoint)
    resumed = OpenNRStudent(config)
    resumed_optimizer = torch.optim.AdamW(resumed.parameters(), lr=1e-4)
    saved = torch.load(checkpoint, weights_only=True)
    resumed.load_state_dict(saved['model'])
    resumed_optimizer.load_state_dict(saved['optimizer'])
    update(model, optimizer)
    update(resumed, resumed_optimizer)
    assert all(torch.equal(a, b) for a, b in zip(model.parameters(), resumed.parameters()))
    model.eval()
    graph = destination / 'smoke.onnx'
    torch.onnx.export(model, (rgb, guides, context), graph,
                      input_names=['rgb', 'guides', 'context'], output_names=['prediction'],
                      opset_version=17, dynamo=False)
    onnx.checker.check_model(onnx.load(graph))
    result = {'status': 'passed', 'device': 'cpu', 'optimizer_resume_exact': True,
              'onnx_checker': True, 'shape': list(model(rgb, guides, context).shape),
              'synthetic_fixture': True, 'model_promotion': False}
    (destination / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
