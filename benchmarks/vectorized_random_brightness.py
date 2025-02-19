# Copyright 2023 The KerasCV Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import time

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf

from keras_cv.layers import RandomBrightness
from keras_cv.layers.preprocessing.base_image_augmentation_layer import (
    BaseImageAugmentationLayer,
)
from keras_cv.utils import preprocessing as preprocessing_utils


class OldRandomBrightness(BaseImageAugmentationLayer):
    """A preprocessing layer which randomly adjusts brightness during training.
    This layer will randomly increase/reduce the brightness for the input RGB
    images.

    At inference time, the output will be identical to the input.
    Call the layer with `training=True` to adjust the brightness of the input.

    Note that different brightness adjustment factors
    will be apply to each the images in the batch.

    Args:
      factor: Float or a list/tuple of 2 floats between -1.0 and 1.0. The
        factor is used to determine the lower bound and upper bound of the
        brightness adjustment. A float value will be chosen randomly between
        the limits. When -1.0 is chosen, the output image will be black, and
        when 1.0 is chosen, the image will be fully white. When only one float
        is provided, eg, 0.2, then -0.2 will be used for lower bound and 0.2
        will be used for upper bound.
      value_range: Optional list/tuple of 2 floats for the lower and upper limit
        of the values of the input data. Defaults to [0.0, 255.0]. Can be
        changed to e.g. [0.0, 1.0] if the image input has been scaled before
        this layer.  The brightness adjustment will be scaled to this range, and
        the output values will be clipped to this range.
      seed: optional integer, for fixed RNG behavior.
    Inputs: 3D (HWC) or 4D (NHWC) tensor, with float or int dtype. Input pixel
      values can be of any range (e.g. `[0., 1.)` or `[0, 255]`)
    Output: 3D (HWC) or 4D (NHWC) tensor with brightness adjusted based on the
      `factor`. By default, the layer will output floats. The output value will
      be clipped to the range `[0, 255]`, the valid range of RGB colors, and
      rescaled based on the `value_range` if needed.
    ```
    """

    def __init__(self, factor, value_range=(0, 255), seed=None, **kwargs):
        super().__init__(seed=seed, force_generator=True, **kwargs)
        if isinstance(factor, float) or isinstance(factor, int):
            factor = (-factor, factor)
        self.factor = preprocessing_utils.parse_factor(
            factor, min_value=-1, max_value=1
        )
        self.value_range = value_range
        self.seed = seed

    def augment_image(self, image, transformation, **kwargs):
        return self._brightness_adjust(image, transformation)

    def augment_label(self, label, transformation, **kwargs):
        return label

    def augment_segmentation_mask(
        self, segmentation_mask, transformation, **kwargs
    ):
        return segmentation_mask

    def augment_bounding_boxes(
        self, bounding_boxes, transformation=None, **kwargs
    ):
        return bounding_boxes

    def get_random_transformation(self, **kwargs):
        rgb_delta_shape = (1, 1, 1)
        random_rgb_delta = self.factor(shape=rgb_delta_shape)
        random_rgb_delta = random_rgb_delta * (
            self.value_range[1] - self.value_range[0]
        )
        return random_rgb_delta

    def _brightness_adjust(self, image, rgb_delta):
        rank = image.shape.rank
        if rank != 3:
            raise ValueError(
                "Expected the input image to be rank 3. Got "
                f"inputs.shape = {image.shape}"
            )
        rgb_delta = tf.cast(rgb_delta, image.dtype)
        image += rgb_delta
        return tf.clip_by_value(image, self.value_range[0], self.value_range[1])

    def get_config(self):
        config = {
            "factor": self.factor,
            "value_range": self.value_range,
            "seed": self.seed,
        }
        base_config = super().get_config()
        return dict(list(base_config.items()) + list(config.items()))


class RandomBrightnessTest(tf.test.TestCase):
    def test_consistency_with_old_impl_rescaled_range(self):
        image_shape = (16, 32, 32, 3)
        fixed_factor = (0.8, 0.8)
        image = tf.random.uniform(shape=image_shape)

        layer = RandomBrightness(factor=fixed_factor)
        old_layer = OldRandomBrightness(factor=fixed_factor)

        output = layer(image)
        old_output = old_layer(image)

        self.assertAllClose(old_output, output)

    def test_consistency_with_old_impl_rgb_range(self):
        image_shape = (16, 32, 32, 3)
        fixed_factor = (0.8, 0.8)
        image = tf.random.uniform(shape=image_shape) * 255.0

        layer = RandomBrightness(factor=fixed_factor)
        old_layer = OldRandomBrightness(factor=fixed_factor)

        output = layer(image)
        old_output = old_layer(image)

        self.assertAllClose(old_output, output)


if __name__ == "__main__":
    # Run benchmark
    (x_train, _), _ = tf.keras.datasets.cifar10.load_data()
    x_train = x_train.astype(np.float32)

    num_images = [1000, 2000, 5000, 10000]
    results = {}
    aug_candidates = [RandomBrightness, OldRandomBrightness]
    aug_args = {"factor": (0.5)}

    for aug in aug_candidates:
        # Eager Mode
        c = aug.__name__
        layer = aug(**aug_args)
        runtimes = []
        print(f"Timing {c}")

        for n_images in num_images:
            # warmup
            layer(x_train[:n_images])

            t0 = time.time()
            r1 = layer(x_train[:n_images])
            t1 = time.time()
            runtimes.append(t1 - t0)
            print(f"Runtime for {c}, n_images={n_images}: {t1-t0}")
        results[c] = runtimes

        # Graph Mode
        c = aug.__name__ + " Graph Mode"
        layer = aug(**aug_args)

        @tf.function()
        def apply_aug(inputs):
            return layer(inputs)

        runtimes = []
        print(f"Timing {c}")

        for n_images in num_images:
            # warmup
            apply_aug(x_train[:n_images])

            t0 = time.time()
            r1 = apply_aug(x_train[:n_images])
            t1 = time.time()
            runtimes.append(t1 - t0)
            print(f"Runtime for {c}, n_images={n_images}: {t1-t0}")
        results[c] = runtimes

        # XLA Mode
        c = aug.__name__ + " XLA Mode"
        layer = aug(**aug_args)

        @tf.function(jit_compile=True)
        def apply_aug(inputs):
            return layer(inputs)

        runtimes = []
        print(f"Timing {c}")

        for n_images in num_images:
            # warmup
            apply_aug(x_train[:n_images])

            t0 = time.time()
            r1 = apply_aug(x_train[:n_images])
            t1 = time.time()
            runtimes.append(t1 - t0)
            print(f"Runtime for {c}, n_images={n_images}: {t1-t0}")
        results[c] = runtimes

    plt.figure()
    for key in results:
        plt.plot(num_images, results[key], label=key)
        plt.xlabel("Number images")

    plt.ylabel("Runtime (seconds)")
    plt.legend()
    plt.savefig("comparison.png")

    # So we can actually see more relevant margins
    del results[aug_candidates[1].__name__]
    plt.figure()
    for key in results:
        plt.plot(num_images, results[key], label=key)
        plt.xlabel("Number images")

    plt.ylabel("Runtime (seconds)")
    plt.legend()
    plt.savefig("comparison_no_old_eager.png")

    # Run unit tests
    tf.test.main()
