from functools import partial
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np
import torch
from torch import Tensor, nn
from torch.nn import functional as F


# Matches src/class_indices.json from the FER-mobilenet project.
EMOTION_LABELS = [
    "Anger",
    "Contempt",
    "Disgust",
    "Fear",
    "Happy",
    "Sadness",
    "Surprise",
]


def _make_divisible(ch, divisor=8, min_ch=None):
    if min_ch is None:
        min_ch = divisor
    new_ch = max(min_ch, int(ch + divisor / 2) // divisor * divisor)
    if new_ch < 0.9 * ch:
        new_ch += divisor
    return new_ch


class ConvBNActivation(nn.Sequential):
    def __init__(
        self,
        in_planes: int,
        out_planes: int,
        kernel_size: int = 3,
        stride: int = 1,
        groups: int = 1,
        norm_layer: Optional[Callable[..., nn.Module]] = None,
        activation_layer: Optional[Callable[..., nn.Module]] = None,
    ):
        padding = (kernel_size - 1) // 2
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        if activation_layer is None:
            activation_layer = nn.ReLU6
        super().__init__(
            nn.Conv2d(
                in_channels=in_planes,
                out_channels=out_planes,
                kernel_size=kernel_size,
                stride=stride,
                padding=padding,
                groups=groups,
                bias=False,
            ),
            norm_layer(out_planes),
            activation_layer(inplace=True),
        )


class SqueezeExcitation(nn.Module):
    def __init__(self, input_c: int, squeeze_factor: int = 4):
        super().__init__()
        squeeze_c = _make_divisible(input_c // squeeze_factor, 8)
        self.fc1 = nn.Conv2d(input_c, squeeze_c, 1)
        self.fc2 = nn.Conv2d(squeeze_c, input_c, 1)

    def forward(self, x: Tensor) -> Tensor:
        scale = F.adaptive_avg_pool2d(x, output_size=(1, 1))
        scale = self.fc1(scale)
        scale = F.relu(scale, inplace=True)
        scale = self.fc2(scale)
        scale = F.hardsigmoid(scale, inplace=True)
        return scale * x


class HSigmoid(nn.Module):
    def __init__(self, inplace=True):
        super().__init__()
        self.relu = nn.ReLU6(inplace=inplace)

    def forward(self, x):
        return self.relu(x + 3) / 6


class HSwish(nn.Module):
    def __init__(self, inplace=True):
        super().__init__()
        self.sigmoid = HSigmoid(inplace=inplace)

    def forward(self, x):
        return x * self.sigmoid(x)


class CA(nn.Module):
    def __init__(self, in_channels, out_channels, reduction=32):
        super().__init__()
        self.pool_w = nn.AdaptiveAvgPool2d((1, None))
        self.pool_h = nn.AdaptiveAvgPool2d((None, 1))
        temp_c = max(8, in_channels // reduction)
        self.conv1 = nn.Conv2d(in_channels, temp_c, kernel_size=1, stride=1, padding=0)
        self.bn1 = nn.BatchNorm2d(temp_c)
        self.act1 = HSwish()
        self.conv2 = nn.Conv2d(temp_c, out_channels, kernel_size=1, stride=1, padding=0)
        self.conv3 = nn.Conv2d(temp_c, out_channels, kernel_size=1, stride=1, padding=0)

    def forward(self, x):
        short = x
        _, _, height, width = x.shape
        x_h = self.pool_h(x)
        x_w = self.pool_w(x).permute(0, 1, 3, 2)
        x_cat = torch.cat([x_h, x_w], dim=2)
        out = self.act1(self.bn1(self.conv1(x_cat)))
        x_h, x_w = torch.split(out, [height, width], dim=2)
        x_w = x_w.permute(0, 1, 3, 2)
        out_h = torch.sigmoid(self.conv2(x_h))
        out_w = torch.sigmoid(self.conv3(x_w))
        return short * out_w * out_h


class MAXCA(nn.Module):
    def __init__(self, in_channels, out_channels, reduction=32):
        super().__init__()
        self.pool_w = nn.AdaptiveMaxPool2d((1, None))
        self.pool_h = nn.AdaptiveMaxPool2d((None, 1))
        temp_c = max(8, in_channels // reduction)
        self.conv1 = nn.Conv2d(in_channels, temp_c, kernel_size=1, stride=1, padding=0)
        self.bn1 = nn.BatchNorm2d(temp_c)
        self.act1 = HSwish()
        self.conv2 = nn.Conv2d(temp_c, out_channels, kernel_size=1, stride=1, padding=0)
        self.conv3 = nn.Conv2d(temp_c, out_channels, kernel_size=1, stride=1, padding=0)

    def forward(self, x):
        short = x
        _, _, height, width = x.shape
        x_h = self.pool_h(x)
        x_w = self.pool_w(x).permute(0, 1, 3, 2)
        x_cat = torch.cat([x_h, x_w], dim=2)
        out = self.act1(self.bn1(self.conv1(x_cat)))
        x_h, x_w = torch.split(out, [height, width], dim=2)
        x_w = x_w.permute(0, 1, 3, 2)
        out_h = torch.sigmoid(self.conv2(x_h))
        out_w = torch.sigmoid(self.conv3(x_w))
        return short * out_w * out_h


class CPSCA(nn.Module):
    def __init__(self, inp, oup, reduction=32):
        super().__init__()
        self.avg_pool_h = nn.AdaptiveAvgPool2d((None, 1))
        self.avg_pool_w = nn.AdaptiveAvgPool2d((1, None))
        self.max_pool_h = nn.AdaptiveMaxPool2d((None, 1))
        self.max_pool_w = nn.AdaptiveMaxPool2d((1, None))

        mip = max(8, inp // reduction)
        self.conv1 = nn.Conv2d(inp, mip, kernel_size=1, stride=1, padding=0)
        self.bn1 = nn.BatchNorm2d(mip)
        self.act = HSwish()
        self.conv_h = nn.Conv2d(mip, oup, kernel_size=1, stride=1, padding=0)
        self.conv_w = nn.Conv2d(mip, oup, kernel_size=1, stride=1, padding=0)

    def forward(self, x):
        identity = x
        _, _, height, width = x.size()
        avg_h = self.avg_pool_h(x)
        avg_w = self.avg_pool_w(x)
        max_h = self.max_pool_h(x)
        max_w = self.max_pool_w(x)

        y_1 = torch.cat([avg_h, max_w.permute(0, 1, 3, 2)], dim=2)
        y_2 = torch.cat([max_h, avg_w.permute(0, 1, 3, 2)], dim=2)
        y = self.conv1(y_1) + self.conv1(y_2)
        y = self.act(self.bn1(y))

        x_h, x_w = torch.split(y, [height, width], dim=2)
        x_w = x_w.permute(0, 1, 3, 2)
        a_h = self.conv_h(x_h).sigmoid()
        a_w = self.conv_w(x_w).sigmoid()
        return identity * a_w * a_h


class InvertedResidualConfig:
    def __init__(
        self,
        input_c: int,
        kernel: int,
        expanded_c: int,
        out_c: int,
        use_se: str,
        activation: str,
        stride: int,
        width_multi: float,
    ):
        self.input_c = self.adjust_channels(input_c, width_multi)
        self.kernel = kernel
        self.expanded_c = self.adjust_channels(expanded_c, width_multi)
        self.out_c = self.adjust_channels(out_c, width_multi)
        self.use_se = use_se
        self.use_hs = activation == "HS"
        self.stride = stride

    @staticmethod
    def adjust_channels(channels: int, width_multi: float):
        return _make_divisible(channels * width_multi, 8)


class InvertedResidual(nn.Module):
    def __init__(self, cnf: InvertedResidualConfig, norm_layer: Callable[..., nn.Module]):
        super().__init__()
        if cnf.stride not in [1, 2]:
            raise ValueError("illegal stride value.")

        self.use_res_connect = cnf.stride == 1 and cnf.input_c == cnf.out_c
        layers: List[nn.Module] = []
        activation_layer = nn.Hardswish if cnf.use_hs else nn.ReLU

        if cnf.expanded_c != cnf.input_c:
            layers.append(
                ConvBNActivation(
                    cnf.input_c,
                    cnf.expanded_c,
                    kernel_size=1,
                    norm_layer=norm_layer,
                    activation_layer=activation_layer,
                )
            )

        layers.append(
            ConvBNActivation(
                cnf.expanded_c,
                cnf.expanded_c,
                kernel_size=cnf.kernel,
                stride=cnf.stride,
                groups=cnf.expanded_c,
                norm_layer=norm_layer,
                activation_layer=activation_layer,
            )
        )

        if cnf.use_se == "SE":
            layers.append(SqueezeExcitation(cnf.expanded_c))
        elif cnf.use_se == "MAXCA":
            layers.append(MAXCA(cnf.expanded_c, cnf.expanded_c))
        elif cnf.use_se == "CA":
            layers.append(CA(cnf.expanded_c, cnf.expanded_c))
        elif cnf.use_se == "CPSCA":
            layers.append(CPSCA(cnf.expanded_c, cnf.expanded_c))

        layers.append(
            ConvBNActivation(
                cnf.expanded_c,
                cnf.out_c,
                kernel_size=1,
                norm_layer=norm_layer,
                activation_layer=nn.Identity,
            )
        )

        self.block = nn.Sequential(*layers)
        self.out_channels = cnf.out_c
        self.is_strided = cnf.stride > 1

    def forward(self, x: Tensor) -> Tensor:
        result = self.block(x)
        if self.use_res_connect:
            result += x
        return result


class MobileNetV3(nn.Module):
    def __init__(
        self,
        inverted_residual_setting: List[InvertedResidualConfig],
        last_channel: int,
        num_classes: int,
        block: Optional[Callable[..., nn.Module]] = None,
        norm_layer: Optional[Callable[..., nn.Module]] = None,
    ):
        super().__init__()
        if not inverted_residual_setting:
            raise ValueError("The inverted_residual_setting should not be empty.")
        if block is None:
            block = InvertedResidual
        if norm_layer is None:
            norm_layer = partial(nn.BatchNorm2d, eps=0.001, momentum=0.01)

        layers: List[nn.Module] = []
        firstconv_output_c = inverted_residual_setting[0].input_c
        layers.append(
            ConvBNActivation(
                3,
                firstconv_output_c,
                kernel_size=3,
                stride=2,
                norm_layer=norm_layer,
                activation_layer=nn.Hardswish,
            )
        )

        for cnf in inverted_residual_setting:
            layers.append(block(cnf, norm_layer))

        lastconv_input_c = inverted_residual_setting[-1].out_c
        lastconv_output_c = 6 * lastconv_input_c
        layers.append(
            ConvBNActivation(
                lastconv_input_c,
                lastconv_output_c,
                kernel_size=1,
                norm_layer=norm_layer,
                activation_layer=nn.Hardswish,
            )
        )

        self.features = nn.Sequential(*layers)
        self.avgpool = nn.AdaptiveAvgPool2d(1)
        self.classifier_1 = nn.Sequential(nn.Linear(lastconv_output_c, last_channel))
        self.classifier_2 = nn.Sequential(
            nn.Hardswish(inplace=True),
            nn.Dropout(p=0.2, inplace=True),
            nn.Linear(last_channel, num_classes),
        )

    def _forward_impl(self, x: Tensor) -> Tensor:
        x = self.features(x)
        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        x_1 = self.classifier_1(x)
        x_2 = self.classifier_2(x_1)
        y_output = torch.log_softmax(x_2, dim=1)
        return x_2, y_output

    def forward(self, x: Tensor) -> Tensor:
        return self._forward_impl(x)


def mobilenet_v3_large(num_classes: int, reduced_tail: bool = True) -> MobileNetV3:
    width_multi = 1.0
    bneck_conf = partial(InvertedResidualConfig, width_multi=width_multi)
    adjust_channels = partial(InvertedResidualConfig.adjust_channels, width_multi=width_multi)
    reduce_divider = 2 if reduced_tail else 1

    inverted_residual_setting = [
        bneck_conf(16, 3, 16, 16, "N", "HS", 1),
        bneck_conf(16, 3, 64, 24, "N", "HS", 2),
        bneck_conf(24, 3, 72, 24, "N", "HS", 1),
        bneck_conf(24, 5, 72, 40, "SE", "HS", 2),
        bneck_conf(40, 5, 120, 40, "SE", "HS", 1),
        bneck_conf(40, 5, 120, 40, "SE", "HS", 1),
        bneck_conf(40, 3, 240, 80, "N", "HS", 2),
        bneck_conf(80, 3, 200, 80, "N", "HS", 1),
        bneck_conf(80, 3, 184, 80, "CPSCA", "HS", 1),
        bneck_conf(80, 3, 184, 80, "CPSCA", "HS", 1),
        bneck_conf(80, 3, 480, 112, "CA", "HS", 1),
        bneck_conf(112, 3, 672, 112, "CA", "HS", 1),
        bneck_conf(112, 5, 672, 160 // reduce_divider, "CA", "HS", 2),
        bneck_conf(160 // reduce_divider, 5, 960 // reduce_divider, 160 // reduce_divider, "CA", "HS", 1),
        bneck_conf(160 // reduce_divider, 5, 960 // reduce_divider, 160 // reduce_divider, "CA", "HS", 1),
    ]
    last_channel = adjust_channels(1280 // reduce_divider)
    return MobileNetV3(
        inverted_residual_setting=inverted_residual_setting,
        last_channel=last_channel,
        num_classes=num_classes,
    )


class EmotionRecognizer:
    def __init__(self, weight_path):
        self.weight_path = Path(weight_path)
        self.device = torch.device("cpu")
        self.model = mobilenet_v3_large(num_classes=len(EMOTION_LABELS))
        checkpoint = torch.load(self.weight_path, map_location=self.device, weights_only=False)
        state_dict = checkpoint["model_state_dict"] if "model_state_dict" in checkpoint else checkpoint
        self.model.load_state_dict(state_dict, strict=True)
        self.model.to(self.device)
        self.model.eval()

    def preprocess_face(self, face_bgr):
        resized = cv2.resize(face_bgr, (224, 224), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        normalized = (rgb - mean) / std
        tensor = torch.from_numpy(normalized.transpose(2, 0, 1)).unsqueeze(0)
        return tensor.to(self.device)

    def predict(self, face_bgr):
        tensor = self.preprocess_face(face_bgr)
        with torch.inference_mode():
            _, log_probabilities = self.model(tensor)
            probabilities = torch.exp(log_probabilities)[0]
            best_index = int(torch.argmax(probabilities).item())
            confidence = float(probabilities[best_index].item())

        return {
            "label": EMOTION_LABELS[best_index],
            "confidence": confidence,
            "scores": {
                label: float(probabilities[index].item())
                for index, label in enumerate(EMOTION_LABELS)
            },
        }
