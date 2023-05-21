import arxiv
import datetime
class PaperGetter:
	def __init__(self):
		self.query = 'ti:%22 Deep Learning %22'
		self.before_date = None
	async def get_papers(self):
		    # 論文の検索
		result = arxiv.Search(
			query=self.query,
			max_results=200,
			sort_by=arxiv.SortCriterion.SubmittedDate,
			sort_order=arxiv.SortOrder.Descending,
		).results()

		# 空なら終了
		result = list(result)
		if len(result) == 0:
			return

		# 取得した論文の中で最新のものの日付を保存

		# 未投稿の論文のみを抽出
		if self.before_date is not None:
			new_results = [data for data in result if data.published.timestamp(
			) > before_date.timestamp()]
			result = new_results
    
		self.before_date = result[0].published
		return result
