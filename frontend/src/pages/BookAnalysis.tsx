import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Checkbox,
  Button,
  Card,
  Col,
  Input,
  InputNumber,
  message,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd';
import type { UploadProps } from 'antd';
import {
  ArrowLeftOutlined,
  CopyOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  PlayCircleOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { bookAnalysisApi, projectApi } from '../services/api';
import type {
  BookAnalyzeResponse,
  BookAnalysisChapterPreview,
  BookSplitResponse,
  PaginationResponse,
  Project,
} from '../types';

const { Title, Text } = Typography;
const { TextArea } = Input;

const MAX_PREVIEW_ROWS = 8;

async function readTextFileWithFallback(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();

  const utf8Decoder = new TextDecoder('utf-8', { fatal: false });
  const utf8Text = utf8Decoder.decode(buffer);
  if (!utf8Text.includes('\uFFFD')) {
    return utf8Text;
  }

  try {
    const gbkDecoder = new TextDecoder('gbk', { fatal: false });
    const gbkText = gbkDecoder.decode(buffer);
    return gbkText || utf8Text;
  } catch {
    return utf8Text;
  }
}

export default function BookAnalysis() {
  const navigate = useNavigate();
  const [sourceText, setSourceText] = useState('');
  const [splitResult, setSplitResult] = useState<BookSplitResponse | null>(null);
  const [analyzeResult, setAnalyzeResult] = useState<BookAnalyzeResponse | null>(null);
  const [loadingSplit, setLoadingSplit] = useState(false);
  const [loadingAnalyze, setLoadingAnalyze] = useState(false);
  const [minChapterLength, setMinChapterLength] = useState(100);
  const [maxChars, setMaxChars] = useState(160000);
  const [startChapter, setStartChapter] = useState<number>(1);
  const [endChapter, setEndChapter] = useState<number>(1);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | undefined>(undefined);
  const [embeddingEnabled, setEmbeddingEnabled] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(false);

  useEffect(() => {
    const loadProjects = async () => {
      try {
        setLoadingProjects(true);
        const data = await projectApi.getProjects();
        const projectList = Array.isArray(data)
          ? data
          : ((data as PaginationResponse<Project>)?.items || []);
        setProjects(projectList);
      } catch (error) {
        console.error(error);
        setProjects([]);
      } finally {
        setLoadingProjects(false);
      }
    };
    void loadProjects();
  }, []);

  const chapterColumns = useMemo(
    () => [
      {
        title: '序号',
        dataIndex: 'index',
        key: 'index',
        width: 80,
      },
      {
        title: '章节号',
        dataIndex: 'chapter_number',
        key: 'chapter_number',
        width: 90,
      },
      {
        title: '标题',
        dataIndex: 'title',
        key: 'title',
        width: 240,
        ellipsis: true,
      },
      {
        title: '字数',
        dataIndex: 'word_count',
        key: 'word_count',
        width: 100,
        render: (value: number) => value.toLocaleString(),
      },
      {
        title: '内容预览',
        dataIndex: 'preview',
        key: 'preview',
      },
    ],
    []
  );

  const handleUpload: UploadProps['beforeUpload'] = async (file) => {
    if (!file.name.toLowerCase().endsWith('.txt')) {
      message.error('当前仅支持 TXT 文件');
      return Upload.LIST_IGNORE;
    }

    try {
      const text = await readTextFileWithFallback(file as File);
      setSourceText(text);
      setSplitResult(null);
      setAnalyzeResult(null);
      message.success(`已加载文件：${file.name}`);
    } catch (error) {
      console.error(error);
      message.error('读取文件失败，请重试');
    }

    return Upload.LIST_IGNORE;
  };

  const runSplit = async () => {
    if (!sourceText.trim()) {
      message.warning('请先输入或上传小说正文');
      return;
    }

    try {
      setLoadingSplit(true);
      const response = await bookAnalysisApi.splitChapters({
        content: sourceText,
        min_chapter_length: minChapterLength,
      });
      setSplitResult(response);
      setAnalyzeResult(null);
      setStartChapter(1);
      setEndChapter(response.total_chapters);
      message.success(`识别完成，共 ${response.total_chapters} 个章节`);
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingSplit(false);
    }
  };

  const runAnalyze = async () => {
    if (!sourceText.trim()) {
      message.warning('请先输入或上传小说正文');
      return;
    }

    if (embeddingEnabled && !selectedProjectId) {
      message.warning('启用 Embedding 写入时，请先选择目标项目');
      return;
    }

    try {
      setLoadingAnalyze(true);
      const response = await bookAnalysisApi.analyzeBook({
        content: sourceText,
        project_id: selectedProjectId,
        enable_embedding: embeddingEnabled,
        start_chapter: startChapter,
        end_chapter: endChapter,
        min_chapter_length: minChapterLength,
        max_chars: maxChars,
      });
      setAnalyzeResult(response);
      message.success('拆书分析完成');
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingAnalyze(false);
    }
  };

  const copyResult = async () => {
    if (!analyzeResult?.result_markdown) return;
    try {
      await navigator.clipboard.writeText(analyzeResult.result_markdown);
      message.success('分析结果已复制');
    } catch {
      message.error('复制失败，请手动复制');
    }
  };

  const downloadResult = () => {
    if (!analyzeResult?.result_markdown) return;
    const blob = new Blob([analyzeResult.result_markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `book-analysis-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const canAnalyze = sourceText.trim().length > 0 && !loadingAnalyze && (!embeddingEnabled || !!selectedProjectId);
  const chapterLimit = splitResult?.total_chapters || 1;

  return (
    <div style={{ padding: 16, minHeight: '100vh', background: '#f5f7fa' }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
                返回主页
              </Button>
              <Title level={4} style={{ margin: 0 }}>拆书分析</Title>
            </Space>
            <Tag color="blue">参考 SmartReads 流程</Tag>
          </Space>
        </Card>

        <Card title="1. 输入正文">
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space wrap>
              <Upload showUploadList={false} beforeUpload={handleUpload}>
                <Button icon={<UploadOutlined />}>上传TXT</Button>
              </Upload>
              <Text type="secondary">支持直接粘贴全文，或上传 TXT 文件。</Text>
            </Space>
            <TextArea
              value={sourceText}
              onChange={(e) => {
                setSourceText(e.target.value);
                setSplitResult(null);
                setAnalyzeResult(null);
              }}
              rows={MAX_PREVIEW_ROWS}
              placeholder="在这里粘贴小说正文..."
            />
          </Space>
        </Card>

        <Card title="2. 章节识别与范围设置">
          <Spin spinning={loadingSplit}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Row gutter={12}>
                <Col xs={24} sm={8}>
                  <Text>最小章节长度</Text>
                  <InputNumber
                    min={20}
                    max={5000}
                    style={{ width: '100%' }}
                    value={minChapterLength}
                    onChange={(value) => setMinChapterLength(value || 100)}
                  />
                </Col>
                <Col xs={24} sm={8}>
                  <Text>分析起始章节</Text>
                  <InputNumber
                    min={1}
                    max={chapterLimit}
                    style={{ width: '100%' }}
                    value={startChapter}
                    onChange={(value) => setStartChapter(value || 1)}
                  />
                </Col>
                <Col xs={24} sm={8}>
                  <Text>分析结束章节</Text>
                  <InputNumber
                    min={1}
                    max={chapterLimit}
                    style={{ width: '100%' }}
                    value={endChapter}
                    onChange={(value) => setEndChapter(value || chapterLimit)}
                  />
                </Col>
              </Row>

              <Button type="primary" icon={<FileSearchOutlined />} onClick={runSplit} disabled={!sourceText.trim()}>
                识别章节
              </Button>

              {splitResult?.note && (
                <Alert type="info" showIcon message={splitResult.note} />
              )}

              {splitResult && (
                <Table<BookAnalysisChapterPreview>
                  rowKey="index"
                  columns={chapterColumns}
                  dataSource={splitResult.chapters}
                  size="small"
                  pagination={{ pageSize: 10 }}
                  scroll={{ x: 900 }}
                />
              )}
            </Space>
          </Spin>
        </Card>

        <Card title="3. 执行拆书分析">
          <Spin spinning={loadingAnalyze}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Row gutter={12}>
                <Col xs={24} sm={8}>
                  <Text>最大分析字符数</Text>
                  <InputNumber
                    min={5000}
                    max={400000}
                    style={{ width: '100%' }}
                    value={maxChars}
                    onChange={(value) => setMaxChars(value || 160000)}
                  />
                </Col>
                <Col xs={24} sm={8}>
                  <Text>写入到项目向量库</Text>
                  <Select
                    allowClear
                    showSearch
                    placeholder="可选：选择一个项目"
                    loading={loadingProjects}
                    style={{ width: '100%' }}
                    value={selectedProjectId}
                    optionFilterProp="label"
                    onChange={(value) => setSelectedProjectId(value)}
                    options={projects.map((project) => ({
                      value: project.id,
                      label: project.title,
                    }))}
                  />
                </Col>
                <Col xs={24} sm={8} style={{ display: 'flex', alignItems: 'flex-end' }}>
                  <Checkbox
                    checked={embeddingEnabled}
                    onChange={(e) => setEmbeddingEnabled(e.target.checked)}
                  >
                    启用 Embedding 写入
                  </Checkbox>
                </Col>
                <Col xs={24} sm={24} style={{ display: 'flex', alignItems: 'flex-end' }}>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={runAnalyze}
                    disabled={!canAnalyze}
                  >
                    开始拆书分析
                  </Button>
                </Col>
              </Row>

              {analyzeResult && (
                <Alert
                  type={analyzeResult.truncated ? 'warning' : 'success'}
                  showIcon
                  message={`已分析章节范围：${analyzeResult.analyzed_range}，输入字符数：${analyzeResult.analyzed_chars.toLocaleString()}`}
                  description={
                    <>
                      {analyzeResult.truncated ? '内容超过限制，已自动截断。可缩小章节范围获得更完整结果。' : ''}
                      {analyzeResult.embedding_enabled
                        ? ` 已写入向量库：${analyzeResult.embedding_saved_count} 条`
                        : ''}
                      {analyzeResult.embedding_error
                        ? ` 向量写入失败：${analyzeResult.embedding_error}`
                        : ''}
                    </>
                  }
                />
              )}

              {analyzeResult && (
                <>
                  <Space>
                    <Button icon={<CopyOutlined />} onClick={copyResult}>复制结果</Button>
                    <Button icon={<DownloadOutlined />} onClick={downloadResult}>下载Markdown</Button>
                  </Space>
                  <TextArea
                    value={analyzeResult.result_markdown}
                    readOnly
                    autoSize={{ minRows: 12, maxRows: 30 }}
                  />
                </>
              )}
            </Space>
          </Spin>
        </Card>
      </Space>
    </div>
  );
}
