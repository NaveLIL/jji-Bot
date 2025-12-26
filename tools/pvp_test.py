from src.games.blackjack import PvPBlackjackGame, Shoe

G = PvPBlackjackGame(player_a_id=1, player_b_id=2, player_a_bet=10, player_b_bet=10, shoe=Shoe())
G.deal_initial()
print('STATE_AFTER_DEAL:', G.state)
print(G.get_discord_payload('Alice','Bob'))
# Player A stands
ok = G.stand(1)
print('A stand ok:', ok, 'state now', G.state)
print(G.get_discord_payload('Alice','Bob'))
# Player B tries to hit
res = G.hit(2)
print('B hit result:', res, 'state now', G.state)
print(G.get_discord_payload('Alice','Bob'))
