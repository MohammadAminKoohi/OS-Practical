package lab

import (
	"archive/tar"
	"compress/gzip"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

func token() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}

func writeJSON(path string, value any) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	tmp := path + "." + token() + ".tmp"
	if err = os.WriteFile(tmp, append(data, '\n'), 0600); err != nil {
		return err
	}
	defer os.Remove(tmp)
	return os.Rename(tmp, path)
}

func sourceFiles(source string) ([]string, error) {
	for _, required := range []string{"Makefile", "src/main.c", "src/run.c", "include/runner.h"} {
		info, err := os.Lstat(filepath.Join(source, filepath.FromSlash(required)))
		if err != nil || !info.Mode().IsRegular() || info.Size() > 16<<20 {
			return nil, fmt.Errorf("source must contain a regular file %s", required)
		}
	}
	files := []string{"Makefile"}
	for _, dir := range []string{"src", "include"} {
		err := filepath.WalkDir(filepath.Join(source, dir), func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.Type()&os.ModeSymlink != 0 {
				return fmt.Errorf("source symlink is not supported: %s; copy the file instead", path)
			}
			if d.IsDir() {
				if strings.HasPrefix(d.Name(), ".") || d.Name() == "__pycache__" {
					return filepath.SkipDir
				}
				return nil
			}
			ext := strings.ToLower(filepath.Ext(path))
			if ext == ".o" || ext == ".pyc" || strings.HasPrefix(d.Name(), ".") {
				return nil
			}
			info, err := d.Info()
			if err != nil {
				return err
			}
			if !info.Mode().IsRegular() || info.Size() > 16<<20 {
				return fmt.Errorf("unsupported source file or file over 16 MiB: %s", path)
			}
			rel, err := filepath.Rel(source, path)
			if err != nil {
				return err
			}
			files = append(files, filepath.ToSlash(rel))
			return nil
		})
		if err != nil {
			return nil, err
		}
	}
	sort.Strings(files)
	return files, nil
}

// snapshot has no host build products and contains the course-owned HW2 judge.
func snapshot(source, output string, assignments ...string) (string, error) {
	files, err := sourceFiles(source)
	if err != nil {
		return "", err
	}
	f, err := os.Create(output)
	if err != nil {
		return "", err
	}
	defer f.Close()
	gz := gzip.NewWriter(f)
	tw := tar.NewWriter(gz)
	hash := sha256.New()
	total := 0
	add := func(name string, data []byte) error {
		total += len(data)
		if total > 32<<20 {
			return fmt.Errorf("source snapshot exceeds 32 MiB")
		}
		if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0644, Size: int64(len(data))}); err != nil {
			return err
		}
		_, err := tw.Write(data)
		return err
	}
	for _, rel := range files {
		data, err := os.ReadFile(filepath.Join(source, filepath.FromSlash(rel)))
		if err != nil {
			return "", err
		}
		fmt.Fprintf(hash, "%s\x00%d\x00", rel, len(data))
		hash.Write(data)
		if err = add("q2/"+rel, data); err != nil {
			return "", err
		}
	}
	assignment := "hw2"
	if len(assignments) > 0 {
		assignment = assignments[0]
	}
	embedded := map[string]string{"agent.py": "agent.py"}
	if assignment == "hw2" {
		embedded["sandbox.py"] = "sandbox.py"
		embedded["hw2/test_langar.py"] = "test_langar.py"
		embedded["hw2/probe.c"] = "probe.c"
	} else {
		err = fs.WalkDir(resources, "resources/semester", func(path string, d fs.DirEntry, e error) error {
			if e != nil {
				return e
			}
			if !d.IsDir() {
				embedded[strings.TrimPrefix(path, "resources/")] = strings.TrimPrefix(path, "resources/semester/")
			}
			return nil
		})
		if err != nil {
			return "", err
		}
	}
	keys := make([]string, 0, len(embedded))
	for name := range embedded {
		keys = append(keys, name)
	}
	sort.Strings(keys)
	for _, name := range keys {
		data, err := resources.ReadFile("resources/" + name)
		if err != nil {
			return "", err
		}
		if err = add("course/"+embedded[name], data); err != nil {
			return "", err
		}
	}
	if err = tw.Close(); err != nil {
		return "", err
	}
	if err = gz.Close(); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), f.Close()
}

func unpackSnapshot(archive, destination string) error {
	f, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		name := filepath.Clean(filepath.FromSlash(h.Name))
		if h.Typeflag != tar.TypeReg || filepath.IsAbs(name) || name == ".." || strings.HasPrefix(name, ".."+string(os.PathSeparator)) || h.Size > 16<<20 {
			return fmt.Errorf("invalid snapshot entry %q", h.Name)
		}
		path := filepath.Join(destination, name)
		if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			return err
		}
		out, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
		if err != nil {
			return err
		}
		_, copyErr := io.CopyN(out, tr, h.Size)
		closeErr := out.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
}
