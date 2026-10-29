.PHONY: all test native portable web android android-gplay
all: native portable
native:
	ziran build --project --locked native
portable:
	python3 scripts/build.py bundle
web:
	python3 scripts/build.py web
# Unsigned release APKs: the normal (also F-Droid) edition and Google Play's.
android:
	python3 scripts/android.py build
android-gplay:
	python3 scripts/android.py build --edition gplay
test:
	python3 tests/assets_test.py
	ziran check --project --locked
	ziran build --project --locked --target=c --exe --entry game_test:main -o build/game-test tests/game_test.zi
	./build/game-test/game_test
	ziran build --project --locked --target=c --define CHOANO_PROGRESS_TEST --exe --entry progress_test:main -o build/progress-test tests/progress_test.zi
	./build/progress-test/progress_test
