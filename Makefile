.PHONY: all test native portable web appimage appimage-test android android-gplay
all: native portable
native:
	ziran build --project --locked native
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
	python3 tests/release_test.py
	python3 tests/desktop_release_test.py
	python3 tests/assets_test.py
	ziran check --project --locked
	ziran build --project --locked --target=c --exe --entry game_test:main -o build/game-test tests/game_test.zi
	./build/game-test/game_test
	ziran build --project --locked --target=c --exe --entry playfield_test:main -o build/playfield-test tests/playfield_test.zi
	./build/playfield-test/playfield_test
	ziran build --project --locked --target=c --define CHOANO_PROGRESS_TEST --exe --entry progress_test:main -o build/progress-test tests/progress_test.zi
	./build/progress-test/progress_test
	ziran build --project --locked --target=c --exe --entry accessories_test:main -o build/accessories-test tests/accessories_test.zi
	./build/accessories-test/accessories_test
	ziran build --project --locked --target=c --exe --entry shell_test:main -o build/shell-test tests/shell_test.zi
	./build/shell-test/shell_test
