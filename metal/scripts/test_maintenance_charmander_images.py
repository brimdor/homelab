"""Only original running images and reviewed recovery receivers are accepted."""

import unittest

import maintenance_charmander_images as subject


class ImageRecoveryTests(unittest.TestCase):
    def test_exact_original_descriptors_and_all_native_programs_compile(self):
        for key in subject.PROFILES:
            for target in subject.TARGETS:
                prefix = subject.bindings(key, target)
                for program in (subject.SOURCE_PROGRAM, subject.RECEIVE_PROGRAM, subject.REGISTER_PROGRAM):
                    compile(prefix + program, 'native-original-image', 'exec')
                self.assertIn("'charmander'", prefix)
                self.assertNotIn('Always', prefix)
        for program in (subject.LAYER_SOURCE, subject.LAYER_RECEIVER):
            compile(program, 'native-original-layer', 'exec')
        self.assertIn("'--expected-digest',LAYER", subject.LAYER_RECEIVER)
        self.assertIn('existing layer recovery intent', subject.LAYER_RECEIVER)

    def test_unreviewed_image_or_receiver_is_refused(self):
        for key, target in [('another-image', 'totodile'), ('strata', 'another-host')]:
            with self.assertRaises(RuntimeError):
                subject.bindings(key, target)


if __name__ == '__main__':
    unittest.main()
