LOCKED := $(if $(wildcard ziran.local.toml),,--locked)

.PHONY: all test input-test native portable web appimage appimage-test android android-gplay
all: native portable
native:
	python3 scripts/build.py native
portable:
	python3 scripts/build.py bundle
web:
	python3 scripts/build.py web
# The Linux release image of the native build, at build/Choano.AppImage.
appimage:
	python3 scripts/desktop_release.py appimage
appimage-test:
	python3 tests/appimage_test.py
# Unsigned release APKs: the normal (also F-Droid) edition and Google Play's.
android:
	python3 scripts/android.py build
android-gplay:
	python3 scripts/android.py build --edition gplay
test:
	python3 scripts/theme.py --check
	python3 tests/release_test.py
	python3 tests/build_test.py
	python3 tests/account_build_test.py
	python3 tests/desktop_release_test.py
	python3 tests/assets_test.py
	ziran check --project $(LOCKED)
	ziran build --project $(LOCKED) --target=c --exe --entry game_test:main -o build/game-test tests/game_test.zi
	./build/game-test/game_test
	ziran build --project $(LOCKED) --target=c --exe --entry playfield_test:main -o build/playfield-test tests/playfield_test.zi
	./build/playfield-test/playfield_test
	ziran build --project $(LOCKED) --target=c --exe --entry presentation_test:main -o build/presentation-test tests/presentation_test.zi
	./build/presentation-test/presentation_test
	ziran build --project $(LOCKED) --target=c --exe --entry tutorial_test:main -o build/tutorial-test tests/tutorial_test.zi
	./build/tutorial-test/tutorial_test
	ziran build --project $(LOCKED) --target=c --define CHOANO_SHOP_TEST --exe --entry shop_test:main -o build/shop-test tests/shop_test.zi
	./build/shop-test/shop_test
	ziran build --project $(LOCKED) --target=c --exe --entry shark_test:main -o build/shark-test tests/shark_test.zi
	./build/shark-test/shark_test
	ziran build --project $(LOCKED) --target=c --exe --entry headwear_test:main -o build/headwear-test tests/headwear_test.zi
	./build/headwear-test/headwear_test
	python3 tests/theme_test.py
	ziran build --project $(LOCKED) --target=c --exe --entry timing_test:main -o build/timing-test tests/timing_test.zi
	./build/timing-test/timing_test
	ziran build --project $(LOCKED) --target=c --define CHOANO_PROGRESS_TEST --exe --entry progress_test:main -o build/progress-test tests/progress_test.zi
	./build/progress-test/progress_test
	python3 tests/progress_storage_test.py
	ziran build --project $(LOCKED) --target=c --exe --entry accessories_test:main -o build/accessories-test tests/accessories_test.zi
	./build/accessories-test/accessories_test
	ziran build --project $(LOCKED) --target=c --exe --entry shell_test:main -o build/shell-test tests/shell_test.zi
	./build/shell-test/shell_test
	ziran build --project $(LOCKED) --target=c --exe --entry audio_test:main -o build/audio-test tests/audio_test.zi
	./build/audio-test/audio_test
	python3 tests/frame_input_test.py

# Actual Frame and portable Apps input contracts; uses an existing VM library.
input-test:
	python3 tests/frame_input_test.py
