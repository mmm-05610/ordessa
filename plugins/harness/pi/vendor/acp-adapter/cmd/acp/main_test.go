package main

import (
	"context"
	"strings"
	"testing"
)

func TestClaudeModeIsNotOfferedByGoBridge(t *testing.T) {
	err := run(context.Background(), []string{"--adapter=claude"})
	if err == nil || !strings.Contains(err.Error(), "claude-agent-acp") {
		t.Fatalf("retired Claude mode must refuse with official adapter guidance, got %v", err)
	}
}
