import numpy as np
from typing import List, Tuple
from scipy.optimize import linear_sum_assignment

from app.config import settings
from app.models.schemas import DetectedFace, TrackedFace

class STrack:
    _count = 0

    def __init__(self, bbox: List[float], score: float, landmarks: List[List[float]]):
        STrack._count += 1
        self.track_id = STrack._count
        self.bbox = np.array(bbox, dtype=np.float32)
        self.score = score
        self.landmarks = landmarks
        self.state = 1
        self.frame_id = 0
        self.tracklet_len = 0
        self.time_since_update = 0

    def update(self, new_track: 'STrack', frame_id: int):
        self.frame_id = frame_id
        self.tracklet_len += 1
        self.bbox = new_track.bbox
        self.score = new_track.score
        self.landmarks = new_track.landmarks
        self.state = 1
        self.time_since_update = 0

    def mark_lost(self):
        self.state = 0

def iou_batch(bboxes1: np.ndarray, bboxes2: np.ndarray) -> np.ndarray:
    if len(bboxes1) == 0 or len(bboxes2) == 0:
        return np.zeros((len(bboxes1), len(bboxes2)), dtype=np.float32)

    b1_x1, b1_y1, b1_x2, b1_y2 = bboxes1[:, 0], bboxes1[:, 1], bboxes1[:, 2], bboxes1[:, 3]
    b2_x1, b2_y1, b2_x2, b2_y2 = bboxes2[:, 0], bboxes2[:, 1], bboxes2[:, 2], bboxes2[:, 3]

    inter_x1 = np.maximum(b1_x1[:, None], b2_x1[None, :])
    inter_y1 = np.maximum(b1_y1[:, None], b2_y1[None, :])
    inter_x2 = np.minimum(b1_x2[:, None], b2_x2[None, :])
    inter_y2 = np.minimum(b1_y2[:, None], b2_y2[None, :])

    inter_w = np.maximum(0.0, inter_x2 - inter_x1)
    inter_h = np.maximum(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    b1_area = (b1_x2 - b1_x1) * (b1_y2 - b1_y1)
    b2_area = (b2_x2 - b2_x1) * (b2_y2 - b2_y1)

    union_area = b1_area[:, None] + b2_area[None, :] - inter_area
    iou = inter_area / np.maximum(union_area, 1e-6)
    return iou

class ByteTrackTracker:
    def __init__(
        self,
        high_thresh: float = settings.TRACK_HIGH_THRESH,
        low_thresh: float = settings.TRACK_LOW_THRESH,
        match_thresh: float = settings.MATCH_THRESH,
        max_time_lost: int = settings.TRACK_BUFFER
    ):
        self.high_thresh = high_thresh
        self.low_thresh = low_thresh
        self.match_thresh = match_thresh
        self.max_time_lost = max_time_lost

        self.tracked_stracks: List[STrack] = []
        self.lost_stracks: List[STrack] = []
        self.frame_id = 0

    def update(self, detected_faces: List[DetectedFace]) -> List[TrackedFace]:
        self.frame_id += 1
        activated_stracks: List[STrack] = []
        lost_stracks: List[STrack] = []
        removed_stracks: List[STrack] = []

        high_dets: List[STrack] = []
        low_dets: List[STrack] = []

        high_thresh = settings.TRACK_HIGH_THRESH
        low_thresh = settings.TRACK_LOW_THRESH

        for face in detected_faces:
            strack = STrack(face.bbox, face.score, face.landmarks)
            if face.score >= high_thresh:
                high_dets.append(strack)
            elif face.score >= low_thresh:
                low_dets.append(strack)

        strack_pool = [st for st in self.tracked_stracks if st.state == 1]
        matches_a, u_track_a, u_det_a = self._match(strack_pool, high_dets, self.match_thresh)

        for trk_idx, det_idx in matches_a:
            strack = strack_pool[trk_idx]
            det = high_dets[det_idx]
            strack.update(det, self.frame_id)
            activated_stracks.append(strack)

        unmatched_stracks = [strack_pool[i] for i in u_track_a]
        matches_b, u_track_b, u_det_b = self._match(unmatched_stracks, low_dets, 0.5)

        for trk_idx, det_idx in matches_b:
            strack = unmatched_stracks[trk_idx]
            det = low_dets[det_idx]
            strack.update(det, self.frame_id)
            activated_stracks.append(strack)

        for i in u_track_b:
            strack = unmatched_stracks[i]
            strack.mark_lost()
            lost_stracks.append(strack)

        for i in u_det_a:
            det = high_dets[i]
            if det.score >= settings.NEW_TRACK_THRESH:
                det.frame_id = self.frame_id
                det.state = 1
                activated_stracks.append(det)

        for strack in self.lost_stracks:
            strack.time_since_update += 1
            if strack.time_since_update > self.max_time_lost:
                removed_stracks.append(strack)
            else:
                lost_stracks.append(strack)

        self.tracked_stracks = [st for st in self.tracked_stracks if st.state == 1] + activated_stracks
        self.lost_stracks = [st for st in self.lost_stracks if st not in removed_stracks and st.state == 0] + lost_stracks

        output_tracked: List[TrackedFace] = []
        for strack in self.tracked_stracks:
            output_tracked.append(TrackedFace(
                track_id=strack.track_id,
                bbox=strack.bbox.tolist(),
                score=strack.score,
                landmarks=strack.landmarks
            ))

        return output_tracked

    def _match(self, tracks: List[STrack], dets: List[STrack], thresh: float) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
        if len(tracks) == 0 or len(dets) == 0:
            return [], list(range(len(tracks))), list(range(len(dets)))

        track_bboxes = np.array([st.bbox for st in tracks], dtype=np.float32)
        det_bboxes = np.array([st.bbox for st in dets], dtype=np.float32)

        ious = iou_batch(track_bboxes, det_bboxes)
        cost_matrix = 1.0 - ious

        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        matches = []
        unmatched_tracks = set(range(len(tracks)))
        unmatched_dets = set(range(len(dets)))

        for r, c in zip(row_ind, col_ind):
            if ious[r, c] >= (1.0 - thresh):
                matches.append((r, c))
                unmatched_tracks.discard(r)
                unmatched_dets.discard(c)

        return matches, list(unmatched_tracks), list(unmatched_dets)

face_tracker = ByteTrackTracker()
