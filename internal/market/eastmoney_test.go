package market

import (
	"encoding/json"
	"testing"
)

func TestFlexFloatParsesNumbersAndMissingValues(t *testing.T) {
	var payload struct {
		A flexFloat `json:"a"`
		B flexFloat `json:"b"`
		C flexFloat `json:"c"`
	}
	if err := json.Unmarshal([]byte(`{"a":12.34,"b":"-","c":null}`), &payload); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if payload.A.ptr() == nil || *payload.A.ptr() != 12.34 {
		t.Fatalf("A = %+v", payload.A)
	}
	if payload.B.ptr() != nil || payload.C.ptr() != nil {
		t.Fatal("missing values should stay nil")
	}
}

func TestStockSecID(t *testing.T) {
	tests := map[string]string{
		"600519": "1.600519",
		"688981": "1.688981",
		"000001": "0.000001",
		"300750": "0.300750",
	}
	for symbol, want := range tests {
		if got := stockSecID(symbol); got != want {
			t.Errorf("stockSecID(%q) = %q, want %q", symbol, got, want)
		}
	}
}
