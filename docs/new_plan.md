My production stack would be:

Face Detection: SCRFD
Face Alignment: SCRFD 5-point landmarks
Face Recognition: AdaFace (primary), ArcFace as a configurable option
Face Quality: FaceQNet or MagFace quality scoring
Liveness (optional): MiniFASNet
Tracking: ByteTrack
Gallery: Multiple embeddings (10–20 per person)
Vector Search: FAISS HNSW initially, with a migration path to Milvus/Qdrant for very large deployments
Registration: Quality-driven capture with automatic pose diversity and duplicate checking
Recognition: Track memory + consensus + confidence thresholds
Storage: PostgreSQL + object storage for images
Inference: ONNX Runtime or TensorRT, with the option to move to NVIDIA Triton as camera counts grow