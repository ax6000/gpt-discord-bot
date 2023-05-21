import openai
import datetime

class Summarizer():
	def __init__(self):
		# self.__key = key
		self.model = "gpt-3.5-turbo"
		self.prompt = """与えられた論文の要点を3点のみでまとめ、以下のフォーマットで日本語で出力してください。```
		タイトルの日本語訳
		・要点1
		・要点2
		・要点3
		```"""

	async def summarize(self,result):
		text = f"title: {result.title}\nbody: {result.summary}"
		response = openai.ChatCompletion.create(
					model=self.model,
					messages=[
						{'role': 'system', 'content': self.prompt},
						{'role': 'user', 'content': text}
					],
					temperature=0.25,
				)
		summary = response['choices'][0]['message']['content']
		tokens = response['usage']['total_tokens']
		title_en = result.title
		title, *body = summary.split('\n')
		body = '\n'.join(body)
		date_str = result.published.strftime("%Y-%m-%d %H:%M:%S")
		message = f"発行日: {date_str}\n{result.entry_id}\n{title_en}\n{title}\n{body}\n"
		
		return message,tokens
