from src.arxiv2discord.arxiv_getter import PaperGetter 
from src.arxiv2discord.summarizer import Summarizer 
class ArxivInterface:
	def __init__(self):
		self.paper_getter = PaperGetter()
		self.summarizer = Summarizer()
		self.channel = None

	async def set_channel(self,channel):
		self.channel = channel

	async def run(self):
		token_used = 0
		papers = self.paper_getter.get_papers()
		summarize_tasks = []
		for paper_data in papers:
			txt,tokens = self.summarizer.summarize(paper_data)
			summarize_tasks.append(txt)
			token_used += tokens
		summarize_results = await asyncio.gather(*summarize_tasks)
		for result in reversed(summarize_results):
			await self.channel.send(result)
		return token_used

