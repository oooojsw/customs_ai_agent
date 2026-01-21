#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
FAISS Index Health Check Script

Usage:
    python check_index_health.py
"""

import sys
import subprocess
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS


def check_git_tracking(index_path):
    """Check if index files are tracked by Git"""
    print("\n" + "="*60)
    print("[Check 1] Git Tracking Status")
    print("="*60)

    try:
        result = subprocess.run(
            ["git", "ls-files", str(index_path)],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )

        tracked_files = [f for f in result.stdout.strip().split('\n') if f]

        if tracked_files:
            print(f"[ERROR] {len(tracked_files)} index files tracked by Git:")
            for f in tracked_files:
                print(f"   - {f}")
            print("\nWARNING: Index files should NOT be tracked by Git!")
            print("Fix:")
            print("   git rm -r --cached config/faiss_index_local/")
            print("   git commit -m \"fix: remove FAISS index from git tracking\"")
            return False
        else:
            print("[OK] Index files not tracked by Git")
            return True

    except Exception as e:
        print(f"[WARNING] Cannot check Git status: {e}")
        return None


def check_index_files(index_path, index_faiss, index_pkl):
    """Check if index files exist"""
    print("\n" + "="*60)
    print("[Check 2] Index Files Existence")
    print("="*60)

    if not index_path.exists():
        print(f"[ERROR] Index directory not found: {index_path}")
        print("\nFix:")
        print("   python quick_rebuild.py")
        return False

    print(f"[OK] Index directory exists: {index_path}")

    files_ok = True

    if index_faiss.exists():
        size_mb = index_faiss.stat().st_size / (1024*1024)
        print(f"[OK] index.faiss exists ({size_mb:.1f} MB)")
    else:
        print("[ERROR] index.faiss not found")
        files_ok = False

    if index_pkl.exists():
        size_mb = index_pkl.stat().st_size / (1024*1024)
        print(f"[OK] index.pkl exists ({size_mb:.1f} MB)")
    else:
        print("[ERROR] index.pkl not found")
        files_ok = False

    if not files_ok:
        print("\nFix:")
        print("   python quick_rebuild.py")

    return files_ok


def check_index_content(index_path):
    """Check index content and quality"""
    print("\n" + "="*60)
    print("[Check 3] Index Content and Quality")
    print("="*60)

    try:
        # Load embedding model
        print("Loading embedding model...")
        embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5"
        )

        # Load index
        print("Loading FAISS index...")
        vector_store = FAISS.load_local(
            str(index_path),
            embeddings,
            allow_dangerous_deserialization=True
        )

        # Check document count
        doc_count = len(vector_store.docstore._dict)
        print(f"[OK] Index loaded successfully")
        print(f"Total documents: {doc_count}")

        # Check content types
        pdf_count = 0
        txt_count = 0
        tiny_count = 0

        for doc_id, doc in vector_store.docstore._dict.items():
            source = doc.metadata.get('source', '')
            content_len = len(doc.page_content)

            if '.pdf' in source.lower():
                pdf_count += 1
            elif '.txt' in source.lower():
                txt_count += 1

            if content_len < 50:
                tiny_count += 1

        print(f"\nDocument Source Statistics:")
        print(f"   PDF chunks: {pdf_count}")
        print(f"   TXT chunks: {txt_count}")
        print(f"   Tiny chunks (<50 chars): {tiny_count}")

        # Evaluate quality
        is_healthy = True

        if doc_count < 1000:
            print(f"\n[WARNING] Document count too low (expected: 7774, actual: {doc_count})")
            print("   Possible reason: Index does not include PDF files")
            is_healthy = False

        if pdf_count < 1000:
            print(f"\n[WARNING] PDF chunks too low (expected: 7706, actual: {pdf_count})")
            print("   Possible reason: PDF files not processed correctly")
            is_healthy = False

        if tiny_count > 10:
            print(f"\n[WARNING] Found {tiny_count} tiny chunks")
            print("   Possible reason: Chunk filter not working")
            is_healthy = False

        if is_healthy:
            print(f"\n[OK] Index quality is good")

        return is_healthy

    except Exception as e:
        print(f"[ERROR] Index loading failed: {e}")
        print("\nFix:")
        print("   python quick_rebuild.py")
        return False


def check_retrieval_quality(index_path):
    """Test retrieval functionality"""
    print("\n" + "="*60)
    print("[Check 4] Retrieval Function Test")
    print("="*60)

    try:
        embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5"
        )
        vector_store = FAISS.load_local(
            str(index_path),
            embeddings,
            allow_dangerous_deserialization=True
        )

        # Test queries
        test_queries = [
            "海关",
            "征税",
            "进出口税则",
            "商品归类"
        ]

        print("\nTest Query Results:")
        all_ok = True

        for query in test_queries:
            try:
                results = vector_store.similarity_search_with_score(query, k=1)

                if results and len(results) > 0:
                    doc, score = results[0]
                    source = doc.metadata.get('source', 'unknown')

                    # Check similarity
                    if score > 0.3:  # Similarity threshold
                        status = "[OK]"
                    else:
                        status = "[WARNING]"
                        all_ok = False

                    print(f"{status} Query: {query}")
                    print(f"   Result: {Path(source).name[:60]}...")
                    print(f"   Score: {score:.4f}")
                else:
                    print(f"[ERROR] Query: {query} - No results")
                    all_ok = False

            except Exception as e:
                print(f"[ERROR] Query: {query} - Error: {e}")
                all_ok = False

        if all_ok:
            print(f"\n[OK] Retrieval function works well")
        else:
            print(f"\n[WARNING] Retrieval function may have issues")

        return all_ok

    except Exception as e:
        print(f"[ERROR] Retrieval test failed: {e}")
        return False


def main():
    """Main function"""
    base_dir = Path(__file__).parent
    index_path = base_dir / "config" / "faiss_index_local"
    index_faiss = index_path / "index.faiss"
    index_pkl = index_path / "index.pkl"

    print("\n" + "="*60)
    print("FAISS Index Health Check")
    print("="*60)
    print(f"Index path: {index_path}")

    from datetime import datetime
    print(f"Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # Check 1: Git tracking
    results['git_tracking'] = check_git_tracking(index_path)

    # Check 2: File existence
    results['files_exist'] = check_index_files(index_path, index_faiss, index_pkl)

    if not results['files_exist']:
        print("\n" + "="*60)
        print("[ERROR] Index files not found, skipping remaining checks")
        print("="*60)
        print("\nSuggestion: Run index rebuild script")
        print("   python quick_rebuild.py")
        return

    # Check 3: Index content
    results['content_quality'] = check_index_content(index_path)

    # Check 4: Retrieval function
    results['retrieval'] = check_retrieval_quality(index_path)

    # Summary
    print("\n" + "="*60)
    print("Check Summary")
    print("="*60)

    status_map = {
        True: "[OK] Pass",
        False: "[ERROR] Fail",
        None: "[WARNING] Skip"
    }

    print(f"\nGit Tracking Status: {status_map.get(results['git_tracking'], '[WARNING] Unknown')}")
    print(f"Files Existence:      {status_map.get(results['files_exist'], '[WARNING] Unknown')}")
    print(f"Index Quality:        {status_map.get(results['content_quality'], '[WARNING] Unknown')}")
    print(f"Retrieval Function:   {status_map.get(results['retrieval'], '[WARNING] Unknown')}")

    # Overall assessment
    all_passed = all(v in [True, None] for v in results.values())

    if all_passed:
        print(f"\n[SUCCESS] All checks passed! Index is healthy.")
    else:
        print(f"\n[WARNING] Issues found, please refer to suggestions above.")
        print(f"\nCommon fix:")
        print(f"   python quick_rebuild.py")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
