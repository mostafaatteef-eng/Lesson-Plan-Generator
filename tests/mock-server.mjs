// Mock backend for frontend failure-handling tests. NOT part of the app.
// MOCK_MODE=401 | 503 | ok controls how mutating endpoints respond.
import express from 'express';

const mode = process.env.MOCK_MODE || '401';
const app = express();

app.use((req, res, next) => {
  res.set('Access-Control-Allow-Origin', '*');
  res.set('Access-Control-Allow-Headers', 'Content-Type, X-App-Passcode');
  res.set('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});

app.get('/api/settings', (_req, res) => {
  res.json({
    institution_ar: 'مدارس ابدأ الوطنية للعلوم التقنية',
    institution_en: 'EBDA National Schools of Applied Technology',
    school_name_ar: 'مدرسة ابدأ الوطنية للعلوم التقنية — بدر',
    school_name_en: 'EBDA National School of Applied Technology – Badr',
    specialization_ar: 'الذكاء الاصطناعي وتحليل البيانات',
    specialization_en: 'Artificial Intelligence & Data Analysis',
    default_grade_level: 'الصف الثاني الثانوي التكنولوجي',
    default_duration_minutes: 45,
    default_academic_year: '٢٠٢٥-٢٠٢٦',
    default_branch: 'الذكاء الاصطناعي وتحليل البيانات',
    default_job_title: 'معلم أول الذكاء الاصطناعي وتحليل البيانات',
    default_knowledge_code: 'TPK04',
    default_location: 'معمل الذكاء الاصطناعي وتحليل البيانات',
    default_teacher_name: '',
    logo_data_url: null,
    logo_filename: null,
    extracted_brand_color: null,
  });
});

const mutating = (req, res) => {
  if (mode === '401') {
    return res.status(401).json({ detail: 'Missing or invalid app passcode.' });
  }
  if (mode === '503') {
    return res
      .status(503)
      .json({ detail: 'This action is disabled until a server-side APP_PASSCODE is configured.' });
  }
  return res.status(500).json({ detail: 'mock mode not implemented' });
};

app.post('/api/curriculum/upload', mutating);
app.post('/api/template/upload', mutating);
app.post('/api/generate', mutating);
app.post('/api/generate-batch', mutating);

app.listen(8910, '127.0.0.1', () => console.log(`mock up, mode=${mode}`));
