package webui

import (
	"embed"
	"io/fs"
)

//go:embed index.html login.html register.html qr_approve.html assets/*
var files embed.FS

func Index() ([]byte, error) {
	return files.ReadFile("index.html")
}

func Login() ([]byte, error) {
	return files.ReadFile("login.html")
}

func Register() ([]byte, error) {
	return files.ReadFile("register.html")
}

func QRApprove() ([]byte, error) {
	return files.ReadFile("qr_approve.html")
}

func Assets() (fs.FS, error) {
	return fs.Sub(files, "assets")
}
