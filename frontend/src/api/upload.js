import request from './request'

/**
 * 上传文件
 */
export function uploadFile(file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  
  return request({
    url: '/upload',
    method: 'post',
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    onUploadProgress: progressEvent => {
      if (onProgress) {
        const percentCompleted = Math.round(
          (progressEvent.loaded * 100) / progressEvent.total
        )
        onProgress(percentCompleted)
      }
    }
  })
}

/**
 * 下载文件
 */
export function downloadFile(filename) {
  return request({
    url: `/upload/download/${filename}`,
    method: 'get',
    responseType: 'blob' // 重要：以blob方式接收文件
  })
}