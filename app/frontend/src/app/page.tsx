'use client';

import { useState, useEffect } from 'react';
import { ArrowUpTrayIcon, ChatBubbleLeftIcon, VideoCameraIcon, KeyIcon, SunIcon, MoonIcon, Cog6ToothIcon, ArrowUpIcon  } from '@heroicons/react/24/outline';

// API configuration
const API_CONFIG = {
  baseURL: '/api', 
  headers: {
    'Content-Type': 'application/json',
  },
  mode: 'cors' as RequestMode,
  credentials: 'include' as RequestCredentials,
};

const getFetchOptions = (method: string, body?: any) => ({
  method,
  headers: API_CONFIG.headers,
  credentials: API_CONFIG.credentials,
  mode: API_CONFIG.mode,
  ...(body && { body: typeof body === 'string' ? body : JSON.stringify(body) })
});

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [isChecked, setIsChecked] = useState(false)
  const [pdfFileName, setPdfFileName] = useState('')
  const [audioFileName, setAudioFileName] = useState('')
  const [pdfFile, setPdfFile] = useState<File>()
  const [audioFile, setAudioFile] = useState<File>()
  const [voiceType, setVoiceType] = useState('default')
  const [voiceSource, setVoiceSource] = useState('upload')
  const [playhtUserId, setPlayhtUserId] = useState('')
  const [playhtApiKey, setPlayhtApiKey] = useState('')
  const [loading, setLoading] = useState(false);
  const [videoUrl, setVideoUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [apiKeySet, setApiKeySet] = useState(false);
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [showChat, setShowChat] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [qaThreshold, setQaThreshold] = useState(0.04);
  const [safetyInstructions, setSafetyInstructions] = useState(
    "1. Only answer questions related to the lecture content\n" +
    "2. Do not provide personal opinions or biases\n" +
    "3. Maintain professional and academic tone\n" +
    "4. If unsure, acknowledge limitations"
  );
  const [progress, setProgress] = useState(-1)
  const [recordingModule, setRecordingModule] = useState<{
    startRecording: () => Promise<void>;
    stopRecording: () => void;
  } | null>(null);
  const [recording, setRecording] = useState(false);
  const [audioURL, setAudioURL] = useState<any>('');
 
  useEffect(() => {
    const checkSession = async () => {
      try {
        const response = await fetch(`${API_CONFIG.baseURL}/check_session`, {
          ...getFetchOptions('GET'),
          // timeout for development
          signal: AbortSignal.timeout(3000)
        });
        
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const {api_key_set, playht_api_key, playht_user_id} = await response.json();
        setApiKeySet(api_key_set);
        playht_api_key && setPlayhtApiKey(playht_api_key)
        playht_user_id && setPlayhtUserId(playht_user_id)
      } catch (error) {
        setError('Failed to connect to server. Make sure backend is running on port 8080');
      }
    };
    checkSession();
}, []);

  // handle theme changes
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);


  useEffect(() => {
    const loadRecording = async () => {
      const module = await import('../utils/recording');
      setRecordingModule({
        startRecording: module.startRecording,
        stopRecording: module.stopRecording
      });
    };
    loadRecording();
  }, []);

  const handleApiKeySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    
    try {
      const response = await fetch(`${API_CONFIG.baseURL}/setup_api`, 
        getFetchOptions('POST', { api_key: apiKey })
      );
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.error || 'Failed to set API key');
      }
      
      if (data.success) {
        setApiKeySet(true);
        setError('');
      } else {
        throw new Error(data.error || 'Failed to set API key');
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to connect to server');
      setApiKeySet(false);
    } finally {
      setLoading(false);
    }
  };

  const handleChange = () => {
    setVoiceType(!isChecked ? "custom" : "default")
    setIsChecked(!isChecked);
  }

  const handleAudioUpload = async (event: any) => {
    const file = event.target.files?.[0];
    setAudioFileName(file?.name)
    setAudioFile(file)
    setAudioURL(URL.createObjectURL(file));
    setVoiceSource('upload')
    setVoiceType('custom')
  }

  const handlePdfUpload = async (event: any) => {
    const file = event.target.files?.[0];
    setPdfFileName(file?.name)
    setPdfFile(file)
  }

  const handleFileUpload = async () => {
      
      if (loading) return;

      const formData = new FormData();
      pdfFile && formData.append('pdf_file', pdfFile);
      formData.append('voice_type', voiceType)
      if (isChecked && voiceType == 'custom') {
        audioFile && formData.append('audio_file', audioFile);
        formData.append('voice_source', voiceSource)
        formData.append('playht_api_key', playhtApiKey)
        formData.append('playht_user_id', playhtUserId)
      }
      setLoading(true);
      setError('');
      
      try {

        if (isChecked && !audioFile) {
          throw new Error('No audio file found.');
        }
        if (isChecked && (!playhtApiKey || !playhtUserId )) {
          throw new Error('Please set your playht key and id.');
        }
        
        const response = await fetch(`${API_CONFIG.baseURL}/upload_file`, {
          method: 'POST',
          body: formData,
          credentials: API_CONFIG.credentials,
          mode: API_CONFIG.mode,
        });
        
        const data = await response.json();
        
        if (!response.ok) {
          if (response.status === 401) {
            setApiKeySet(false);
            throw new Error('API key not set. Please set your API key first.');
          }
          throw new Error(data.error || 'Error uploading file');
        }

        
        if (data.msg == 'successfuly uploaded') {
          subscribeToProgress()
        } else {
          throw new Error('Invalid response from server');
        }

      } catch (error) {
        setError(error instanceof Error ? error.message : 'Error uploading file');
      }
  };

  const subscribeToProgress = () => {
    const evtSource = new EventSource(`${API_CONFIG.baseURL}/upload_progress`);
    evtSource.onmessage = (event) => {
      setProgress(() => event.data)
      if (event.data.includes("Process complete")) {
        const urlPart = event.data.split("Video available at:")[1];
        if (urlPart) {
          setVideoUrl(urlPart.trim());
          setShowChat(true);
          setError('');
        }
        setLoading(false);
        evtSource.close();
      }
    };
    evtSource.onerror = (err) => {
      setError("Error occurred during file processing");
      setLoading(false);
      evtSource.close();
    };
  };

  const handleAskQuestion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    setLoading(true);
    setError('');

    try {
      const response = await fetch(`${API_CONFIG.baseURL}/ask`, 
        getFetchOptions('POST', { question })
      );

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Error getting answer');
      }

      const data = await response.json();
      setAnswer(data.answer);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Error getting answer');
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadVideo = async () => {
    if (!videoUrl) return;
    
    try {
      // Clean up the video path to avoid double static
      const cleanPath = videoUrl.replace('/api/static/', '').replace('static/', '');
      window.location.href = `${API_CONFIG.baseURL}/download_video?video_path=${encodeURIComponent(cleanPath)}`;
    } catch (error) {
      setError('Error downloading video');
    }
  };

  const handleUpdateSettings = async () => {
    try {
      const response = await fetch(`${API_CONFIG.baseURL}/update_qa_settings`,
        getFetchOptions('POST', { 
          threshold: qaThreshold,
          safety_instructions: safetyInstructions
        })
      );
      
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to update settings');
      }
      
      setShowSettings(false);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to update settings');
    }
  };

  // settings panel component
  const SettingsPanel = () => {

    const [localThreshold, setLocalThreshold] = useState(qaThreshold);
    const [localInstructions, setLocalInstructions] = useState(safetyInstructions);

    const handleSave = async () => {
      try {
        const response = await fetch(`${API_CONFIG.baseURL}/update_qa_settings`,
          getFetchOptions('POST', { 
            threshold: localThreshold,
            safety_instructions: localInstructions
          })
        );
        
        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.error || 'Failed to update settings');
        }
        
        setQaThreshold(localThreshold);
        setSafetyInstructions(localInstructions);
        setShowSettings(false);
      } catch (error) {
        setError(error instanceof Error ? error.message : 'Failed to update settings');
      }
    };

    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div className="bg-white dark:bg-gray-800 rounded-xl p-6 max-w-md w-full mx-4 max-h-[calc(100vh-20px)] overflow-y-scroll scrollbar-custom">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-semibold">Chat Settings</h3>
            <button
              onClick={() => setShowSettings(false)}
              className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              ✕
            </button>
          </div>
          
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Content Relevance Threshold
              </label>
              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min="0.01"
                  max="0.10"
                  step="0.01"
                  value={localThreshold}
                  onChange={(e) => setLocalThreshold(parseFloat(e.target.value))}
                  className="w-full"
                />
                <span className="text-sm text-gray-600 dark:text-gray-400 w-16">
                  {localThreshold.toFixed(2)}
                </span>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Higher values (0.10) require questions to be more closely related to the content.
                Lower values (0.01) allow more flexible questions but may reduce relevance.
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Safety Instructions
              </label>
              <textarea
                value={localInstructions}
                onChange={(e) => setLocalInstructions(e.target.value)}
                rows={6}
                className="w-full px-4 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                placeholder="Enter safety instructions for the AI..."
              />
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                These instructions will guide how the AI responds to questions.
              </p>
            </div>

            <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg">
              <h4 className="text-sm font-medium text-blue-800 dark:text-blue-300 mb-2">
                Tips for Safety Instructions
              </h4>
              <ul className="text-sm text-blue-700 dark:text-blue-400 space-y-1">
                <li>• Be clear and specific about allowed topics</li>
                <li>• Define the tone and style of responses</li>
                <li>• Set boundaries for sensitive information</li>
                <li>• Include error handling guidelines</li>
              </ul>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowSettings(false)}
                className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg"
              >
                Save Settings
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const handleRecording = async () => {
    if (!recordingModule) return;

    if (recording) {
      const blob = await recordingModule.stopRecording();
      // @ts-ignore-next-line (ignores the next line)
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url);
      
      await new Promise<void>((resolve) => {
        audio.onloadedmetadata = () => resolve();
        setTimeout(resolve, 1000); 
      });
      // @ts-ignore-next-line (ignores the next line)
      const file = new File([blob], 'recorded_voice.mp3', { type: 'audio/mp3' });
      setAudioFile(file)
      setAudioURL(url);
      setAudioFileName('recorded.mp3')
      setVoiceSource('record')
      setVoiceType('custom')
    } else {
      await recordingModule.startRecording();
    }
    setRecording(!recording);
  };

  return (
    <main className="min-h-screen bg-white dark:bg-gradient-to-br dark:from-gray-900 dark:to-gray-800 text-gray-900 dark:text-white transition-colors duration-200">
      <div className="container mx-auto px-4 py-16">
        {/* Add theme toggle button */}
        <button
          onClick={() => setIsDarkMode(!isDarkMode)}
          className="fixed top-4 right-4 p-2 rounded-lg bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors"
        >
          {isDarkMode ? (
            <SunIcon className="h-6 w-6" />
          ) : (
            <MoonIcon className="h-6 w-6" />
          )}
        </button>

        <div className="text-center mb-16">
          <h1 className="text-5xl font-bold mb-4 bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-purple-600 dark:from-blue-400 dark:to-purple-500">
            MAESTRO
          </h1>
          <p className="text-gray-600 dark:text-gray-300">
            Transform your presentations into engaging videos with AI
          </p>
        </div>

        <div className="max-w-3xl mx-auto">
          <div className="bg-gray-100 dark:bg-gray-800 rounded-xl p-8 shadow-2xl">
            <div className="space-y-8">
              {/* API Key Setup */}
              {!apiKeySet && (
                <div className="space-y-4">
                  <div className="flex items-center space-x-2">
                    <KeyIcon className="h-6 w-6 text-gray-500 dark:text-gray-400" />
                    <h3 className="text-lg font-semibold">Set up your OpenAI API Key</h3>
                  </div>
                  <form onSubmit={handleApiKeySubmit} className="space-y-4">
                    <input
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="Enter your OpenAI API key"
                      className="w-full px-4 py-2 bg-white dark:bg-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                      required
                    />
                    <button
                      type="submit"
                      className="w-full bg-blue-500 hover:bg-blue-600 text-white font-semibold px-6 py-2 rounded-lg transition-colors"
                      disabled={loading}
                    >
                      {loading ? 'Setting up...' : 'Set API Key'}
                    </button>
                  </form>
                </div>
              )}

              {/* Error Display */}
              {error && (
                <div className="bg-red-500/10 border border-red-500/50 text-red-500 px-4 py-2 rounded-lg">
                  {error}
                </div>
              )}

              {/* Loading State */}
              {loading && (
                // <div className="text-center py-4">
                //   <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-400 mx-auto"></div>
                //   <p className="mt-4 text-gray-400">Processing your request... Please grab a cup of coffee while we work ☕</p>
                // </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="">
                        {progress > 1 &&
                          <div className="flex items-center">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="size-6 w-6 h-6 mr-2 text-green-500">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
                            </svg>
                            <span>Images generated for slides</span>
                          </div>
                        }
                        {progress == 1 &&  
                          <div className="flex items-center">
                            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-400 mr-2"></div>
                            <span>Generating images for slides ...</span>
                          </div>
                        }
                  </div>
                  <div className="">
                        {progress > 2 &&
                          <div className="flex items-center">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="size-6 w-6 h-6 mr-2 text-green-500">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
                            </svg>
                            <span>Scripts generated for slides</span>
                          </div>
                        }
                        {progress == 2 &&
                          <div className="flex items-center">
                            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-400 mr-2"></div>
                            <span>Generating scripts for slides ...</span>
                          </div>
                        }
                  </div>
                  <div className="">
                        {progress > 3 &&
                          <div className="flex items-center">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="size-6 w-6 h-6 mr-2 text-green-500">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
                            </svg>
                            <span>Audio generated for slides</span>
                          </div>
                        }
                        {progress == 3 &&
                          <div className="flex items-center">
                            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-400 mr-2"></div>
                            <span>Generating audio for slides ...</span>
                          </div>
                        }
                  </div>
                  <div className="">
                        {progress > 4 &&
                          <div className="flex items-center">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="size-6 w-6 h-6 mr-2 text-green-500">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
                            </svg>
                            <span>Video generated for slides</span>
                          </div>
                        }
                        {progress == 4 &&
                          <div className="flex items-center">
                            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-400 mr-2"></div>
                            <span>Generating video for slides...</span>
                          </div>
                        }
                  </div>
                  <div className="col-span-2 justify-center">
                        {progress == 5 &&
                          <div className="flex justify-center items-center">
                            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-400 mr-2"></div>
                            <span>Combining All ...</span>
                          </div>
                        }
                  </div>
                </div>
              )}

              {/* File Upload Section */}
              {apiKeySet && !videoUrl && (
                <>
                  <div className="relative border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-8 text-center">
                    <span className="absolute text-gray-500 bg-gray-100 dark:bg-gray-800 left-2 -top-3 px-2">Upload Slide</span>
                    <input
                      type="file"
                      accept=".pdf"
                      onChange={handlePdfUpload}
                      className="hidden"
                      id="file-upload"
                      required
                    />
                    <label
                      htmlFor={loading ? "" : "file-upload"}
                      className={`flex flex-col items-center ${loading ? "cursor-default" : "cursor-pointer"}`}

                    >
                      <ArrowUpTrayIcon className="h-12 w-12 text-gray-400 mb-4" />
                      <span className={`text-lg font-medium ${loading ? "text-gray-500" : " text-gray-300"}`}>
                        {pdfFileName ? `${pdfFileName}` : 'Drop your PDF here or click to upload'}
                      </span>
                      <span className="text-sm text-gray-500 mt-2">
                        PDF files up to 50MB
                      </span>
                    </label>
                  </div>
                  <div className={`relative ${isChecked ? "" : "!mt-0"}`}>
                    {isChecked && <span className="absolute text-gray-500 bg-gray-100 dark:bg-gray-800 left-2 -top-3 px-2 z-1">Upload Voice</span>}
                    <div className={`border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-center flex flex-col items-center transition-all duration-300 ease-in-out overflow-hidden ${isChecked ? 'p-8 opacity-100 h-auto' : 'opacity-0 h-0'}`}>
                      <input className="w-full mb-2 px-4 py-2 bg-white dark:bg-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none" onChange={(e) => setPlayhtApiKey(e.target.value)} value={playhtApiKey} type="password" placeholder="Playht API Key" required/>
                      <input className="w-full mb-2 px-4 py-2 bg-white dark:bg-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none" onChange={(e) => setPlayhtUserId(e.target.value)} value={playhtUserId} type="password" placeholder="Playht User Id" required/>
                      <div className="w-full flex items-center justify-between">
                          {/* Upload MP3 */}
                          <div className="flex-1 bg-blue-500 text-white font-semibold rounded-lg transition-colors mr-1">
                              <label htmlFor="custom_voice" className="w-full cursor-pointer py-2 block">
                                Upload 
                              </label>
                              <input type="file" id="custom_voice" className="hidden" onChange={handleAudioUpload} name="custom_voice" accept=".mp3"/>
                          </div>
                          
                          {/* Record Voice */}
                          <button 
                            onClick={handleRecording}
                            disabled={!navigator.mediaDevices}
                            className="flex-1 bg-blue-500 text-white font-semibold py-2 rounded-lg transition-colors ml-1"
                          >
                            {recording ? 
                                        <div className="flex justify-center items-center">
                                          <div className="w-4 h-4 mr-1 rounded-full bg-red-500/80 animate-[pulse_.75s_ease-in-out_infinite] hover:animate-none"></div>
                                          Stop
                                        </div>
                                        : 
                                        <div>Record</div> 
                                        }
                          </button>
                      </div>
                    </div>
                  </div>
                  {isChecked && audioURL && (
                      <div className="relative border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-8 text-center flex flex-col items-center justify-center">
                        <span className="absolute text-gray-500 bg-gray-100 dark:bg-gray-800 left-2 -top-3 px-2">Check Voice</span>
                        <audio 
                          src={audioURL} 
                          controls 
                          className="my-2 h=[40px]"
                        />
                        <div className={`text-lg font-medium ${loading ? "text-gray-500" : " text-gray-300"}`}>
                          {audioFileName ? `${audioFileName}` : ''}
                        </div>
                      </div>
                        )}
                  <div className="!mt-2 flex items-center">
                    <input type="checkbox" checked={isChecked} onChange={handleChange} className="appearance-none w-5 h-5 cursor-pointer rounded border border-slate-300 bg-transparent checked:bg-blue-600 relative after:absolute after:content-[''] after:block after:w-2 after:h-3 after:border-r-2 after:border-b-2 after:border-white after:rotate-45 after:top-1/2 after:left-1/2 after:-translate-x-1/2 after:-translate-y-1/2 checked:after:opacity-100 after:opacity-0 transition-all focus:ring-0"/>
                    <span className="text-gray-500 ml-2">Use custom voice</span>
                  </div>
                  <button className={`w-full bg-blue-500 text-white font-semibold px-6 py-2 rounded-lg transition-colors !mt-2 ${loading ? "cursor-default" : "cursor-pointer"}`} onClick={handleFileUpload}>Generate Video</button>
                </>
              )}

              {/* Video and Chat Section */}
              {videoUrl && (
                <div className="space-y-6">
                  {/* Action Buttons */}
                  <div className="flex justify-between items-center mb-4">
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          setVideoUrl('');
                          setShowChat(false);
                          setFile(null);
                          setQuestion('');
                          setAnswer('');
                          setIsChecked(false)
                          setPdfFileName('')
                          setAudioFileName('')
                        }}
                        className="bg-blue-500 hover:bg-blue-600 text-white font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
                      >
                        <ArrowUpTrayIcon className="h-5 w-5" />
                        Upload New File
                      </button>
                      <button
                        onClick={() => {
                          setApiKeySet(false);
                          setApiKey('');
                          setVideoUrl('');
                          setShowChat(false);
                          setFile(null);
                          setQuestion('');
                          setAnswer('');
                          // Clear session
                          fetch(`${API_CONFIG.baseURL}/clear_session`, getFetchOptions('POST'));
                        }}
                        className="bg-gray-600 hover:bg-gray-700 text-white font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
                      >
                        <KeyIcon className="h-5 w-5" />
                        Change API Key
                      </button>
                    </div>
                    <button
                      onClick={handleDownloadVideo}
                      className="bg-green-500 hover:bg-green-600 text-white font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <ArrowUpTrayIcon className="h-5 w-5" />
                      Download Video
                    </button>
                  </div>
                  
                  {/* Video Player */}
                  {videoUrl && (
                    <div className="relative aspect-video w-full bg-gray-900 rounded-lg overflow-hidden">
                      <video 
                        controls 
                        className="w-full h-full"
                        src={videoUrl} // update video source
                      >
                        Your browser does not support the video tag.
                      </video>
                    </div>
                  )}
                </div>
              )}

              {/* Chat Section */}
              {showChat && (
                <div className="mt-8 space-y-4">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-2">
                      <ChatBubbleLeftIcon className="h-6 w-6 text-gray-500 dark:text-gray-400" />
                      <h3 className="text-lg font-semibold">Ask Questions</h3>
                    </div>
                    <button
                      onClick={() => setShowSettings(true)}
                      className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                      title="Chat Settings"
                    >
                      <Cog6ToothIcon className="h-6 w-6" />
                    </button>
                  </div>
                  
                  {/* Chat Messages */}
                  {answer && (
                    <div className="bg-gray-100 dark:bg-gray-700/50 rounded-lg p-4 mb-4">
                      <p className="text-gray-700 dark:text-gray-300">{answer}</p>
                    </div>
                  )}
                  
                  {/* Question Input*/}
                  <form onSubmit={handleAskQuestion} className="space-y-4">
                    <div className="relative flex gap-2">
                      <textarea
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                        placeholder="Ask a question about the content..."
                        className="flex-1 pl-4 pr-9 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg focus:ring-2 focus:ring-blue-500 outline-none min-h-[100px] max-h-[200px] resize-y overflow-auto scrollbar-custom"
                      />
                      <button
                        type="submit"
                        className="absolute right-3 bottom-3 bg-blue-500 hover:bg-blue-600 text-white font-semibold px-2 py-2 rounded-lg transition-colors flex items-center gap-2"
                        disabled={loading}
                      >
                        {loading ? (
                          <>
                            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                          </>
                        ) : (
                          <>
                            <ArrowUpIcon strokeWidth={2} className="h-5 w-5" />
                          </>
                        )}
                      </button>
                    </div>
                  </form>
                  
                  {/* Error Display with light theme */}
                  {error && (
                    <div className="bg-red-100 dark:bg-red-500/10 border border-red-200 dark:border-red-500/50 text-red-600 dark:text-red-500 px-4 py-2 rounded-lg">
                      {error}
                    </div>
                  )}
                </div>
              )}

              {/* Features Grid */}
              {!videoUrl && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="bg-white dark:bg-gray-700 rounded-lg p-6">
                    <VideoCameraIcon className="h-8 w-8 text-blue-500 dark:text-blue-400 mb-4" />
                    <h3 className="text-lg font-semibold mb-2">
                      AI Video Generation
                    </h3>
                    <p className="text-gray-600 dark:text-gray-400">
                      Convert your presentations into professional videos with AI narration
                    </p>
                  </div>
                  <div className="bg-white dark:bg-gray-700 rounded-lg p-6">
                    <ChatBubbleLeftIcon className="h-8 w-8 text-purple-500 dark:text-purple-400 mb-4" />
                    <h3 className="text-lg font-semibold mb-2">
                      Interactive Chat
                    </h3>
                    <p className="text-gray-600 dark:text-gray-400">
                      Ask questions about your content and get instant answers
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* settings panel */}
      {showSettings && <SettingsPanel />}
    </main>
  );
}