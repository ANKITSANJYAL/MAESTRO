import RecordRTC from 'recordrtc';

let recorder: any;
let stream: MediaStream;

export const startRecording = async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new RecordRTC(stream, {
      type: 'audio',
      mimeType: 'audio/webm',
    });
    recorder.startRecording();
    // return true;
  } catch (err) {
    console.error('Error starting recording:', err);
    // return false;
  }
};

export const stopRecording = async () => {
  return new Promise<Blob | null>((resolve) => {
    if (recorder) {
      recorder.stopRecording(() => {
        const blob = recorder.getBlob();
        stream?.getTracks().forEach(track => track.stop());
        recorder.destroy();
        resolve(blob);
      });
    } else {
      resolve(null);
    }
  });
};