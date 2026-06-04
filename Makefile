# arche-web-server build. Pure arche — no C, no --link (networking is a core
# arche feature: the `socket` opaque type + `#import net`). Uses the `arche`
# compiler from PATH (install it system-wide); override with `make ARCHE=/path/to/arche`.
ARCHE ?= arche
SRC_DIR := src
MAIN := $(SRC_DIR)/main.arche
ARCHE_SRCS := $(wildcard $(SRC_DIR)/*.arche)
BIN := server

.PHONY: all run clean test

all: $(BIN)

$(BIN): $(ARCHE_SRCS)
	$(ARCHE) build -o $(BIN) $(MAIN)

run: $(BIN)
	./$(BIN) 8080 www

clean:
	rm -f $(BIN)

test: $(BIN)
	python3 tests/integration/test_http.py
